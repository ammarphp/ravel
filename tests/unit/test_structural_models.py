"""Fabricated located proposals and inert ordinary APIs; no model/native calls."""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import subprocess

import pytest
from ravel.workflow import structural_models as sm, physics_knowledge as pk
from ravel.workflow import research_tools as tools, research_cycle as cycle
from ravel.workflow import agent_host, agent_graph, execution


@pytest.fixture(autouse=True)
def no_external_calls(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('no process/provider/UFO import admitted by structural source controls')
    monkeypatch.setattr(subprocess, 'Popen', deny)
    monkeypatch.setattr(execution, 'runtime_context', lambda: {'inert_source_control': True,
        'environment_sha256': execution.digest(execution.runtime_environment())})


def pin(path):
    path = path.resolve(); raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, allow_nan=False) + '\n')
    return pin(path)


def field(identity='S', **changes):
    result = {'id': identity, 'twice_spin': 0, 'cp': 'even', 'color_dynkin': [0, 0],
        'weak_dynkin': [0], 'hypercharge': '0', 'self_conjugate': True,
        'conjugation': 'self', 'conjugate_of': None, 'node_ids': ['basis']}
    result.update(changes); return result


def model(identity, kind='prior', fields=None):
    return {'id': identity, 'name': 'Explicit fabricated ' + identity, 'kind': kind,
        'conventions': {'gauge_basis': 'SU(3)c x SU(2)L x U(1)Y', 'phase': 'pre-EWSB',
            'hypercharge_normalization': 'Q=T3+Y', 'cp_convention': 'supplied toy intrinsic-CP definition',
            'field_population': 'new-source-declared-fields', 'node_ids': ['basis']},
        'fields': [field()] if fields is None else fields,
        'interactions': [{'statement': 'Supplied toy lambda S^4', 'node_ids': ['basis']}],
        'kinetic_terms': None, 'topologies': [], 'processes': None,
        'outcomes': [{'status': 'failed', 'statement': 'Supplied prior construction failed; retained.', 'node_ids': ['basis']}],
        'ufo': None, 'node_ids': ['basis']}


def fixture(base, models=None, proposal=None):
    base = base.resolve(); source = base/'source.txt'
    source.write_text('Explicit synthetic scalar proposal annotations, not a physical reference.\n'
                      'Conflicting toy interaction assertion remains unresolved.\n')
    lines = source.read_bytes().splitlines(keepends=True)
    def node(identity, line):
        return {'id': identity, 'kind': 'fact', 'statement': lines[line-1].decode().strip(),
            'tags': ['structural-toy'], 'domain': ['toy'], 'conventions': ['synthetic-only'],
            'applicability': 'Fabricated engineering assertion, not physics qualification.', 'equations': [],
            'evidence': [{'source': 'source', 'line_start': line, 'line_end': line,
                'excerpt_sha256': hashlib.sha256(lines[line-1]).hexdigest(), 'locator': 'synthetic line '+str(line)}],
            'obligations': []}
    graph = {'schema_version': 1, 'id': 'toy-knowledge', 'sources': [{'id': 'source', 'pin': pin(source),
        'citation': 'Own synthetic software fixture', 'version': 'toy1', 'format': 'text', 'parents': []}],
        'nodes': [node('basis', 1), node('conflict', 2)], 'edges': [{'id': 'retained-conflict',
            'kind': 'contradicts', 'source': 'basis', 'target': 'conflict',
            'statement': 'Supplied incompatible toy source assertions retained.', 'assessment': 'located_source_conflict'}]}
    library = {'schema_version': 1, 'id': 'toy-library', 'models': [model('old')] if models is None else models}
    proposed = model('new', 'proposal') if proposal is None else proposal
    request = {'schema_version': 2, 'knowledge': write(base/'knowledge.json', graph),
        'query': {'text': 'Compare the supplied proposed fields', 'tags': [], 'roots': [], 'domain': ['toy'], 'max_nodes': 8},
        'structural_query': {'library': write(base/'library.json', library), 'proposal': write(base/'proposal.json', proposed)}}
    return request, library, proposed


def revise(base, request, library, proposal):
    request['structural_query']['library'] = write(base/'library.json', library)
    request['structural_query']['proposal'] = write(base/'proposal.json', proposal)


def test_exact_multiset_retains_finer_structure_failures_and_knowledge_conflicts(tmp_path):
    request, library, proposed = fixture(tmp_path)
    proposed['interactions'][0]['statement'] = 'Different supplied S^6 interaction'
    revise(tmp_path, request, library, proposed)
    packet = pk.retrieve(request, tmp_path); record = packet['structural_models']
    match = record['matches'][0]
    assert match['match'] == 'exact' and match['complete_field_correspondence']
    assert match['interactions_equal'] is None and match['physical_equivalence'] is None
    assert not match['novelty_established'] and not record['scientific_acceptance']
    assert record['models'][0]['record']['outcomes'][0]['status'] == 'failed'
    assert record['models'][0]['record']['kinetic_terms'] is None
    assert record['models'][0]['record']['topologies'] == []
    assert record['query']['record']['interactions'] != record['models'][0]['record']['interactions']
    assert packet['contradictions'][0]['id'] == 'retained-conflict'
    assert not any(packet['claims'].values()) and record['omitted_models'] == []
    assert {Path(p['path']).name for p in pk.input_pins(request, tmp_path)} == {
        'knowledge.json', 'source.txt', 'library.json', 'proposal.json',
        'structural_models.py', 'physics_knowledge.py', 'research_followup.py', 'research_cycle.py'}
    assert {'library.json', 'proposal.json'} <= {Path(p['path']).name for p in packet['premises'][0]['basis']}


def test_rational_canonicalization_names_order_and_multiplicity(tmp_path):
    old = model('old', fields=[field('A', hypercharge='2/4'), field('B', hypercharge='-1/3')])
    new = model('new', 'proposal', [field('renamedB', hypercharge='-2/6'), field('renamedA', hypercharge='1/2')])
    request, library, proposal = fixture(tmp_path, [old], new)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'exact' and len(match['correspondence']) == 2
    library['models'][0]['fields'].append(field('extra', hypercharge='1/2'))
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'partial' and not match['complete_field_correspondence']
    assert match['prior_field_count'] == 3 and len(match['unmatched_prior']) == 1


@pytest.mark.parametrize('property', list(sm.FEATURES))
def test_null_property_never_becomes_an_exact_match(tmp_path, property):
    request, library, proposal = fixture(tmp_path)
    proposal['fields'][0][property] = None
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'partial' and property in match['correspondence'][0]['unknown']


@pytest.mark.parametrize('property,value', [('hypercharge_normalization', 'Q=T3+Y/2'),
    ('phase', 'broken-phase'), ('gauge_basis', 'different declared gauge basis')])
def test_convention_conflicts_are_not_converted_or_called_physical_refutation(tmp_path, property, value):
    request, library, proposal = fixture(tmp_path)
    proposal['conventions'][property] = value
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'conflicting' and match['convention_conflicts'][0]['property'] == property
    assert 'hypercharge' not in match['correspondence'][0]['known_equal']
    assert 'hypercharge' in match['correspondence'][0]['incomparable']
    assert match['physical_equivalence'] is None


def test_colour_conjugate_and_charge_sign_are_distinct(tmp_path):
    request, library, proposal = fixture(tmp_path)
    proposal['fields'][0].update(color_dynkin=[1, 0], hypercharge='1/3', self_conjugate=False, conjugation='independent')
    library['models'][0]['fields'][0].update(color_dynkin=[0, 1], hypercharge='-1/3', self_conjugate=False, conjugation='independent')
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'conflicting' and not match['complete_field_correspondence']
    assert set(match['incompatible_pairs'][0]['differing']) == {'color_dynkin', 'hypercharge'}


def test_identical_selected_and_complete_field_scope_are_not_identified(tmp_path):
    request, library, proposal = fixture(tmp_path)
    proposal['conventions']['field_population'] = 'selected-process-fields-only'
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'conflicting'
    assert match['convention_conflicts'][0]['property'] == 'field_population'


@pytest.mark.parametrize('property', list(sm.CONVENTIONS))
def test_unknown_comparison_convention_prevents_exactness(tmp_path, property):
    request, library, proposal = fixture(tmp_path)
    proposal['conventions'][property] = None
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'partial' and property in match['unknown_conventions']


def test_different_cp_convention_keeps_intrinsic_labels_incomparable(tmp_path):
    request, library, proposal = fixture(tmp_path)
    proposal['conventions']['cp_convention'] = 'another explicit CP convention'
    revise(tmp_path, request, library, proposal)
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'conflicting'
    assert 'cp' in match['correspondence'][0]['incomparable']
    assert 'cp' not in match['correspondence'][0]['known_equal']


def test_augmenting_correspondence_matches_independent_exhaustive_oracle():
    # Unknown first occurrence must not consume the sole compatible scalar
    # slot. An independent permutation oracle covers every 3x3 spin pattern.
    for qs in itertools.product((None, 0, 1), repeat=3):
        for ps in itertools.product((0, 1), repeat=3):
            q = {'record': model('q', 'proposal'), 'normalized_fields': [field('q'+str(i), twice_spin=s) for i,s in enumerate(qs)]}
            p = {'record': model('p'), 'normalized_fields': [field('p'+str(i), twice_spin=s) for i,s in enumerate(ps)]}
            oracle = any(all(a is None or a == ps[j] for a,j in zip(qs, order))
                         for order in itertools.permutations(range(3)))
            result = sm.compare(q, p)
            assert result['complete_field_correspondence'] == oracle
            if None in qs and oracle:
                assert result['match'] == 'partial'


def test_empty_field_content_remains_a_coarse_match_not_interaction_equality(tmp_path):
    request, _, _ = fixture(tmp_path, [model('old', fields=[])], model('new', 'proposal', []))
    match = pk.retrieve(request, tmp_path)['structural_models']['matches'][0]
    assert match['match'] == 'exact' and match['query_field_count'] == 0
    assert match['interactions_equal'] is None and not match['novelty_established']


@pytest.mark.parametrize('fault', ['bool-spin', 'float-hypercharge', 'dimension-as-dynkin', 'duplicate-field',
    'missing-conjugate', 'unknown-node', 'duplicate-model', 'unknown-property', 'unknown-status', 'bool-schema', 'unlocated-prior'])
def test_malformed_annotations_and_unsupported_claims_refuse(tmp_path, fault):
    request, library, proposal = fixture(tmp_path)
    f = proposal['fields'][0]
    if fault == 'bool-spin': f['twice_spin'] = True
    elif fault == 'float-hypercharge': f['hypercharge'] = .5
    elif fault == 'dimension-as-dynkin': f['color_dynkin'] = 3
    elif fault == 'duplicate-field': proposal['fields'].append(deepcopy(f))
    elif fault == 'missing-conjugate': f.update(conjugation='conjugate', conjugate_of='absent')
    elif fault == 'unknown-node': f['node_ids'] = ['absent']
    elif fault == 'duplicate-model': library['models'].append(deepcopy(library['models'][0]))
    elif fault == 'unknown-property': f['physics_verified'] = True
    elif fault == 'unknown-status': library['models'][0]['outcomes'][0]['status'] = 'validated-model'
    elif fault == 'bool-schema': library['schema_version'] = True
    else:
        graph = json.loads((tmp_path/'knowledge.json').read_text()); graph['nodes'][0].update(kind='hypothesis', evidence=[])
        request['knowledge'] = write(tmp_path/'knowledge.json', graph)
    revise(tmp_path, request, library, proposal)
    with pytest.raises(ValueError): pk.retrieve(request, tmp_path)


def test_query_unknown_conventions_and_empty_library_are_not_novelty_certificates(tmp_path):
    request, library, proposal = fixture(tmp_path, [])
    proposal['conventions']['hypercharge_normalization'] = None
    revise(tmp_path, request, library, proposal)
    record = pk.retrieve(request, tmp_path)['structural_models']
    assert record['matches'] == [] and record['complete_model_ids'] == []
    assert record['query']['record']['conventions']['hypercharge_normalization'] is None
    assert not record['scientific_acceptance']


def test_complete_node_model_and_packet_bounds_refuse_without_dropping_records(tmp_path, monkeypatch):
    request, library, proposal = fixture(tmp_path)
    request['query']['max_nodes'] = 1
    with pytest.raises(ValueError, match='cannot discard'): pk.retrieve(request, tmp_path)
    request['query']['max_nodes'] = 8
    library['models'] = [model('old'+str(i)) for i in range(sm.MAX_MODELS+1)]
    revise(tmp_path, request, library, proposal)
    with pytest.raises(ValueError): pk.retrieve(request, tmp_path)
    library['models'] = [model('old')]; revise(tmp_path, request, library, proposal)
    monkeypatch.setattr(pk, 'MAX_PACKET_BYTES', 1)
    with pytest.raises(ValueError, match='packet'): pk.retrieve(request, tmp_path)


@pytest.mark.parametrize('which', ['library', 'proposal'])
def test_changed_and_aliased_annotation_bytes_refuse(tmp_path, which):
    request, _, _ = fixture(tmp_path)
    path = tmp_path/(which+'.json'); path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError): pk.retrieve(request, tmp_path)
    original = tmp_path/(which+'-original.json'); path.rename(original); path.symlink_to(original)
    with pytest.raises(ValueError): pk.input_pins(request, tmp_path)


def test_late_library_mutation_after_knowledge_read_is_not_recaptured(tmp_path, monkeypatch):
    request, _, _ = fixture(tmp_path); original = pk.retrieve
    def changed(ordinary, base):
        packet = original(ordinary, base)
        if ordinary['schema_version'] == 1:
            p = tmp_path/'library.json'; p.write_bytes(p.read_bytes()+b' ')
        return packet
    monkeypatch.setattr(pk, 'retrieve', changed)
    with pytest.raises(ValueError, match='changed'): sm.retrieve(request, tmp_path)


def attach_ufo(base, request, library, proposal):
    # Existing source-only fixture supplies canonical literal Particle/Vertex
    # declarations; its code is parsed and never imported.
    from test_model_sarah import write_ufo
    from ravel.physics import ufo_interop
    base = base.resolve(); root = base/'ufo'; write_ufo(root)
    (root/'__init__.py').write_bytes(b'')
    (root/'extra.py').write_text("raise RuntimeError('must never import supplied source')\n")
    manifest = write(base/'ufo-tree.json', ufo_interop.source_tree(root))
    proposal['ufo'] = {'tree': {'root': str(root), 'manifest': manifest},
        'particle_conventions': [{'pdg': 25, 'spin': 1, 'color': 1, 'charge': 0,
            'mass_parameter': 'MH', 'width_parameter': 'WH'}], 'field_pdgs': [{'field': 'S', 'pdg': 25}]}
    revise(base, request, library, proposal)
    return root


def test_optional_ufo_keeps_full_custom_source_empty_member_and_unknown_associations(tmp_path):
    request, library, proposal = fixture(tmp_path); root = attach_ufo(tmp_path, request, library, proposal)
    packet = pk.retrieve(request, tmp_path); observed = packet['structural_models']['query']['ufo_observation']
    assert {'particles', 'parameters', 'vertices', 'couplings', 'lorentz'} <= observed['census'].keys()
    assert 'extra.py' in observed['source_tree']['files'] and '__init__.py' in observed['source_tree']['files']
    assert next(p for p in packet['source_inventory'] if p['path'] == str(root/'__init__.py'))['size'] == 0
    check = observed['field_associations'][0]
    assert check['declared_2s_matches_literal_ufo_2s_plus_1'] is True
    assert check['cp_ew_hypercharge_dynkin_association'] == 'not_inferred'
    assert not observed['model_imported'] and not observed['physical_model_validated']


def test_ufo_conflicting_annotation_is_preserved_not_corrected(tmp_path):
    request, library, proposal = fixture(tmp_path); attach_ufo(tmp_path, request, library, proposal)
    proposal['fields'][0]['twice_spin'] = 2
    revise(tmp_path, request, library, proposal)
    observed = pk.retrieve(request, tmp_path)['structural_models']['query']['ufo_observation']
    assert observed['field_associations'][0]['declared_2s_matches_literal_ufo_2s_plus_1'] is False
    assert not observed['physical_model_validated']


@pytest.mark.parametrize('fault', ['changed', 'added', 'alias', 'missing-field', 'mismatch-pdg'])
def test_complete_ufo_membership_and_declared_association_refuse(tmp_path, fault):
    request, library, proposal = fixture(tmp_path); root = attach_ufo(tmp_path, request, library, proposal)
    if fault == 'changed': (root/'extra.py').write_text('# changed\n')
    elif fault == 'added': (root/'added.py').write_text('# extra member\n')
    elif fault == 'alias':
        (root/'extra.py').unlink(); (root/'extra.py').symlink_to(root/'particles.py')
    elif fault == 'missing-field': proposal['ufo']['field_pdgs'][0]['field'] = 'absent'
    else: proposal['ufo']['field_pdgs'][0]['pdg'] = 11
    if fault in ('missing-field', 'mismatch-pdg'): revise(tmp_path, request, library, proposal)
    with pytest.raises(ValueError): pk.retrieve(request, tmp_path)


def test_ordinary_host_graph_uses_exact_structural_dependencies_and_captured_identity(tmp_path):
    request, _, _ = fixture(tmp_path); rp = write(tmp_path/'request.json', request)
    inputs = [{'id': 'request', 'path': rp['path'], 'sha256': rp['sha256']}] + [
        {'id': 'dep'+str(i), 'path': p['path'], 'sha256': p['sha256']} for i,p in enumerate(pk.input_pins(request, tmp_path))]
    node = {'id': 'models', 'kind': 'tool', 'role': 'proposer', 'depends_on': [], 'inputs': inputs,
        'packet': None, 'action': 'physics-knowledge', 'parameters': {'request_input': 'request'}, 'max_attempts': 1}
    spec = {'schema_version': 1, 'graph_id': 'structural-proposals', 'budget': {'max_nodes': 1,
        'max_calls': 1, 'max_output_tokens': 0, 'max_wall_seconds': 30, 'max_reworks': 0}, 'nodes': [node]}
    graph = tmp_path/'graph'; agent_graph.create(graph, spec); host = agent_host.AgentHost()
    result = agent_graph.execute(graph, host, workers=1)
    assert result['complete'] and result['usage']['calls'] == 1
    assert sm.__name__ in host.identity['sources']
    assert agent_graph.execute(graph, host, workers=1)['usage']['calls'] == 1
    bad = deepcopy(spec); bad['graph_id'] = 'missing-proposal'
    bad['nodes'][0]['inputs'] = [i for i in inputs if i['path'] != request['structural_query']['proposal']['path']]
    other = tmp_path/'bad-graph'; agent_graph.create(other, bad)
    assert not agent_graph.execute(other, host, workers=1)['complete']


def test_current_structural_context_reaches_existing_ordinary_proposal_preparation(tmp_path, monkeypatch):
    from test_research_tools import prepared
    from ravel.workflow import research_blueprint as blueprint
    from test_research_cycle import write as cycle_write
    # Existing helper declares a fresh 1MiB source/64KiB API-context budget;
    # no inherited cycle limit is enlarged and no Graph/model is executed.
    root, _, _, value, _, _ = prepared(tmp_path, monkeypatch)
    request, _, _ = fixture(tmp_path); rp = write(tmp_path/'model-request.json', request)
    packet = pk.retrieve(request, tmp_path)
    mapping = {p['id']: 'model-'+p['id'] for p in packet['premises']}
    before = deepcopy(cycle._load(root)[1]['contract'])
    tools.prepare_model_proposals(root, rp, premise_map=mapping, reason='Source-declared toy models and all conflicts.')
    state = cycle._load(root)[1]
    assert state['contract'] == before and not state['resource_ledger']
    assert state['knowledge_bindings'][-1]['packet'] == packet
    value['context'] = blueprint.prepare_context(root, root/'model-design-context')
    request_pin = cycle_write(tmp_path/'model-blueprint.json', value)
    bundle_pin = tools.prepare(root, request_pin, root/'model-api-context')
    bundle = json.loads(Path(bundle_pin['path']).read_text())
    delivered = bundle['research_facts']['knowledge_contexts'][0]['packet']['structural_models']
    assert delivered == packet['structural_models']
    assert bundle['question'] == before['question'] and bundle['scope'] == before['scope']
    assert not bundle['execution_authorized'] and not bundle['physics_validated']
    tools.check_binding(bundle_pin, tmp_path)
    p = tmp_path/'proposal.json'; p.write_bytes(p.read_bytes()+b' ')
    with pytest.raises(ValueError): tools.check_binding(bundle_pin, tmp_path)


def test_incomplete_premise_mapping_keeps_existing_cycle_unchanged(tmp_path):
    from test_research_cycle import contract
    root = tmp_path/'cycle'; before = cycle.create(root, contract(tmp_path), base_dir=tmp_path, evaluation_harness=True)
    request, _, _ = fixture(tmp_path); rp = write(tmp_path/'request.json', request)
    with pytest.raises(ValueError): tools.prepare_model_proposals(root, rp, premise_map={}, reason='Incomplete mapping refuses.')
    assert cycle._load(root)[1] == before


def test_old_schema1_remains_the_existing_kernel(tmp_path):
    from test_physics_knowledge import fixture as original_fixture
    request, _, _ = original_fixture(tmp_path)
    result = pk.retrieve(request, tmp_path)
    assert 'structural_models' not in result and result['selection']['selected_ids'] == ['beam', 'contested']
    assert result['claims'] == {'physics_verified': False, 'execution_authorized': False}
