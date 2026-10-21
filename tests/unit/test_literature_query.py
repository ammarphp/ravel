"""Controls for literature query expansion and its one governed model choice.

Vocabularies and queries are fictional. The model transport is an inert Host
fixture; subprocesses are refused, so no process, provider or model is reached.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ravel.validation import check_agent_paths
from ravel.workflow import agent_graph as graph, agent_host, literature_provider, literature_query as q

FICTIONAL = {'schema_version': 1, 'kind': 'literature-query-vocabulary', 'note': 'Fictional notation for controls.',
    'entries': [
        {'id': 'glimmer-momentum', 'class': 'observable', 'forms': [
            {'text': 'glimmer momentum'}, {'text': 'GM', 'case': 'exact'}, {'text': 'p_G'}, {'text': 'glimmer impulse'}]},
        {'id': 'missing-glimmer-momentum', 'class': 'observable', 'forms': [
            {'text': 'missing glimmer momentum'}, {'text': 'MGM', 'case': 'exact'}, {'text': 'G_vanish'}]},
        {'id': 'quuxon', 'class': 'particle', 'forms': [
            {'text': 'quuxon'}, {'text': '\\tilde{x}'}, {'text': 'QX', 'case': 'exact'}, {'text': 'qux', 'trigger': False}]},
        {'id': 'zorp-boson', 'class': 'particle', 'forms': [{'text': "Zorp'"}, {'text': 'heavy zorp boson'}]},
        {'id': 'wibble-method', 'class': 'statistics', 'forms': [{'text': 'XLs'}, {'text': 'wibble method'}]},
        {'id': 'wibble-level', 'class': 'statistics', 'forms': [{'text': 'XL', 'case': 'exact'}, {'text': 'wibble level'}]},
        {'id': 'florp-region', 'class': 'region', 'forms': [
            {'text': 'florp region'}, {'text': 'FR', 'case': 'exact'}, {'text': 'florp zone'}, {'text': 'zone of florp'}]}]}


def vocabulary(tmp_path, document=None, name='vocabulary.json'):
    path = tmp_path / name
    path.write_text(json.dumps(FICTIONAL if document is None else document))
    return str(path)


def offered(result):
    return [t['text'] for t in result['terms']]


def reasons(result):
    return {(o['text'], o['reason']) for o in result['omitted']}


def test_shipped_vocabulary_is_valid_generic_and_supports_common_notation():
    shipped = q.load_vocabulary()
    assert len(shipped['entries']) >= 100 and len({e['id'] for e in shipped['entries']}) == len(shipped['entries'])
    assert shipped['sha256'] == hashlib.sha256(Path(q.VOCABULARY).read_bytes()).hexdigest()
    for query, entry in [('E_{\\mathrm{T}}^{\\mathrm{miss}} tails', 'missing-transverse-momentum'),
                         ("a Z′ decaying to leptons", 'heavy-neutral-gauge-boson'),
                         ('pair-produced LLPs', 'long-lived-particle'), ('two b-jets', 'b-jet'),
                         ('√s dependence', 'centre-of-mass-energy'), ('g̃ pair production', 'gluino'),
                         ('a χ̃₁⁰ mass scan', 'neutralino'), ('τ̃ pairs', 'tau-slepton'),
                         ('tt̄ events', 'top-quark-pair'), ('t\\bar{t} events', 'top-quark-pair')]:
        assert entry in {m['entry'] for m in q.expand(query)['matches']}, query
    # Each sparticle tilde binds to its own base, never to the next particle.
    assert [m['entry'] for m in q.expand('t̃ → t χ̃⁰₁')['matches']] == ['top-squark', 'neutralino']
    # Ordinary words that spell an abbreviation never start an expansion.
    assert q.expand('criteria met by the document PDF before we stop')['matches'] == []


def test_expansion_is_deterministic_bounded_and_search_contract_valid(tmp_path):
    path = vocabulary(tmp_path)
    first = q.expand('quuxon decays with missing glimmer momentum', vocabulary=path)
    assert first == q.expand('quuxon decays with missing glimmer momentum', vocabulary=path)
    body = {k: v for k, v in first.items() if k != 'sha256'}
    assert first['sha256'] == hashlib.sha256(q._canonical(body)).hexdigest()
    assert first['expanded_query'].startswith(first['query'] + '; ')
    assert first['model'] == {'status': 'not_requested'} and first['search_hint_only'] is True
    assert first['source_vocabulary'] is None
    args = {'query': first['expanded_query'], 'top_k': 5, 'mode': 'hybrid', 'document_scope': [], 'filters': {}}
    assert literature_provider._validate(args, 'search_args') == args
    shipped = q.expand('MET and b-jets with a Z′ in signal regions')
    assert len(shipped['expanded_query']) <= q.MAX_QUERY_CHARS and shipped['terms']


def test_longest_match_wins_and_matched_concepts_do_not_overlap(tmp_path):
    result = q.expand('missing glimmer momentum spectrum', vocabulary=vocabulary(tmp_path))
    assert [(m['entry'], m['form'], m['tokens']) for m in result['matches']] == [
        ('missing-glimmer-momentum', 'missing glimmer momentum', [0, 3])]
    assert 'GM' not in offered(result) and 'MGM' in offered(result)


def test_case_exact_forms_plurals_notation_and_output_only_forms(tmp_path):
    path = vocabulary(tmp_path)
    assert q.expand('the gm of the run', vocabulary=path)['matches'] == []
    assert [m['entry'] for m in q.expand('GM spectra', vocabulary=path)['matches']] == ['glimmer-momentum']
    assert [m['entry'] for m in q.expand('two QXs and quuxons', vocabulary=path)['matches']] == ['quuxon', 'quuxon']
    for spelling in ("Zorp'", 'Zorp′', 'zorp prime', 'ZORP’'):
        assert [m['entry'] for m in q.expand(spelling + ' search', vocabulary=path)['matches']] == ['zorp-boson']
    assert q.expand('a qux', vocabulary=path)['matches'] == []
    assert 'qux' in offered(q.expand('a quuxon', vocabulary=path))
    # Typesetting commands and accents carry no meaning for matching.
    assert q._words('E_{\\mathrm{T}}^{\\mathrm{miss}}') == q._words('E_T^miss')
    # A combining tilde or bar reads before its base, as \tilde{g} is written; a script change separates tokens.
    assert q._words('g̃ and σ') == ['tilde', 'g', 'and', 'sigma']
    assert q._words('χ̃⁰₁') == q._words('\\tilde{\\chi}^0_1') == ['tilde', 'chi', '0', '1']
    assert q._words('ℓ̃ and tt̄') == q._words('\\tilde{\\ell} and t\\bar{t}')
    assert [m['entry'] for m in q.expand('x̃ pairs', vocabulary=path)['matches']] == ['quuxon']


def test_tie_prefers_the_form_matched_without_capital_plural_folding(tmp_path):
    path = vocabulary(tmp_path)
    assert [m['entry'] for m in q.expand('XLs here', vocabulary=path)['matches']] == ['wibble-method']
    assert [m['entry'] for m in q.expand('XL here', vocabulary=path)['matches']] == ['wibble-level']


def test_present_and_redundant_forms_are_omitted_with_reasons(tmp_path):
    result = q.expand('quuxon and QX decays', vocabulary=vocabulary(tmp_path))
    assert offered(result) == ['\\tilde{x}', 'qux']
    assert {('quuxon', 'present_in_query'), ('QX', 'present_in_query')} <= reasons(result)
    # A form whose every lexical token is already searched adds nothing for the BM25 half.
    redundant = q.expand('florp region yields', vocabulary=vocabulary(tmp_path))
    assert offered(redundant) == ['FR', 'florp zone'] and ('zone of florp', 'no_new_lexical_token') in reasons(redundant)


def test_term_entry_and_query_length_caps(tmp_path):
    path = vocabulary(tmp_path)
    capped = q.expand('quuxon with GM', vocabulary=path, limits={'max_terms': 2})
    assert len(capped['terms']) == 2 and any(o['reason'] == 'term_cap' for o in capped['omitted'])
    per_entry = q.expand('quuxon', vocabulary=path, limits={'max_terms_per_entry': 1})
    assert offered(per_entry) == ['\\tilde{x}'] and ('qux', 'entry_cap') in reasons(per_entry)
    query = 'quuxon ' + 'z' * (q.MAX_QUERY_CHARS - 9)
    long = q.expand(query, vocabulary=path)
    assert long['expanded_query'] == query and long['terms'] == []
    assert {o['reason'] for o in long['omitted'] if o['text'] != 'quuxon'} == {'query_length_cap'}


@pytest.mark.parametrize('query', ['', '   ', 'x' * (q.MAX_QUERY_CHARS + 1), None, b'quuxon'])
def test_query_must_be_bounded_nonblank_text(tmp_path, query):
    with pytest.raises(ValueError, match='nonblank text'):
        q.expand(query, vocabulary=vocabulary(tmp_path))


@pytest.mark.parametrize('limits', [{'max_terms': 65}, {'max_terms_per_entry': 0}, {'max_terms': True},
                                    {'max_model_terms': -1}, {'unknown': 1}, []])
def test_limits_are_closed_and_bounded(tmp_path, limits):
    with pytest.raises(ValueError, match='limit'):
        q.expand('quuxon', vocabulary=vocabulary(tmp_path), limits=limits)


def _edited(change):
    document = deepcopy(FICTIONAL)
    change(document)
    return document


@pytest.mark.parametrize('document, message', [
    (_edited(lambda d: d['entries'].append(deepcopy(d['entries'][0]))), 'unique slug'),
    (_edited(lambda d: d['entries'][0]['forms'].append({'text': 'XLs'})), 'ambiguous trigger'),
    (_edited(lambda d: d['entries'][0]['forms'].append({'text': 'Glimmer Momentum'})), 'distinct nonempty'),
    (_edited(lambda d: d['entries'][0]['forms'].append({'text': 'x'})), 'one-character'),
    (_edited(lambda d: d['entries'][0]['forms'].append({'text': 'gmx', 'case': 'exact'})), 'capital letter'),
    (_edited(lambda d: d['entries'][0]['forms'].append({'text': 'gmx', 'case': 'upper'})), 'case fold/exact'),
    (_edited(lambda d: d['entries'][4]['forms'].__setitem__(0, {'text': 'XLs', 'trigger': False}) or
             d['entries'][4]['forms'].__setitem__(1, {'text': 'wibble method', 'trigger': False})), 'trigger form'),
    (_edited(lambda d: d['entries'][0].__setitem__('class', 'analysis')), 'known query vocabulary class'),
    (_edited(lambda d: d['entries'][0].__setitem__('class', ['observable'])), 'known query vocabulary class'),
    (_edited(lambda d: d['entries'][0].__setitem__('id', 'Glimmer')), 'unique slug'),
    (_edited(lambda d: d['entries'][0]['forms'].append({'text': 'tab\there'})), 'printable'),
    (_edited(lambda d: d.__setitem__('kind', 'other')), 'unsupported'),
    (_edited(lambda d: d.__setitem__('extra', 1)), 'exact fields'),
])
def test_curated_vocabulary_rejects_ambiguous_or_malformed_entries(tmp_path, document, message):
    with pytest.raises(ValueError, match=message):
        q.expand('quuxon', vocabulary=vocabulary(tmp_path, document))


@pytest.mark.parametrize('raw', ['{"schema_version": 1, "schema_version": 1}', '{"schema_version": NaN}', '[' * 100000])
def test_vocabulary_json_is_finite_and_unique(tmp_path, raw):
    path = tmp_path / 'raw.json'
    path.write_text(raw)
    with pytest.raises(ValueError):
        q.load_vocabulary(path)


def test_source_vocabulary_and_known_tokens_take_token_collections():
    assert q.source_vocabulary(['Quuxons recoiling']) == frozenset({'quuxon', 'recoil'})
    with pytest.raises(ValueError):
        q.source_vocabulary('quuxon')
    with pytest.raises(ValueError):
        q.expand('quuxon', known_tokens='quuxon')
    with pytest.raises(ValueError):
        q.source_vocabulary([1])


# Governed model choice: one charged Graph call through the ordinary Host, transport inert.

QUERY = 'quuxon production with missing glimmer momentum'
PROTOCOL = ['Choose fictional closed entries only.', 'Return empty lists otherwise.']
ROLES = {'aliases': {}, 'roles': {q.ROLE: {'card': {'id': q.ROLE, 'protocol': PROTOCOL}}}}


def test_module_authors_no_instruction_text_or_direct_model_reach():
    source = Path(q.__file__).read_text()
    assert check_agent_paths.scan_source(source, module='ravel.workflow.literature_query',
                                         path='ravel/workflow/literature_query.py', is_package=False) == []


@pytest.fixture
def inert(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError('no process, provider or model dispatch in expansion controls')
    monkeypatch.setattr(subprocess, 'Popen', refuse)
    def run(root, spec, reply):
        host = agent_host.AgentHost()
        monkeypatch.setattr(host, '_responses', lambda data, parameters, request, control: host._result(
            deepcopy(reply), parameters, request, observed_model='explicit-inert-fixture',
            usage={'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}))
        graph.create(root, spec)
        return graph.execute(root, host)
    return run


def prepared(tmp_path, query=QUERY, path=None, **limits):
    base = tmp_path.resolve()
    path = path or vocabulary(base)
    document = q.request_document(query, vocabulary=path, limits=limits or None, roles=ROLES)
    pin = q.write_request(base / 'expansion/request.json', document, vocabulary=path, roles=ROLES)
    spec = q.graph_spec(pin, graph_id='expansion-control', model='explicit-inert-fixture', reasoning_effort='low',
                        vocabulary=path, roles=ROLES)
    return base, path, pin, spec


def reply(pin, entries=(), terms=()):
    return {'kind': q.CHOICE_KIND, 'request_sha256': pin['sha256'], 'entries': list(entries), 'terms': list(terms)}


def test_graph_spec_is_one_bounded_call_with_a_closed_choice(tmp_path):
    _, path, pin, spec = prepared(tmp_path)
    assert spec['budget'] == {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 1024, 'max_wall_seconds': 300,
                              'max_reworks': 0}
    (node,) = spec['nodes']
    assert node['kind'] == 'model' and node['max_attempts'] == 1 and node['depends_on'] == []
    assert node['parameters']['instructions'] == ' '.join(PROTOCOL)
    assert node['inputs'] == [{'id': q.INPUT_ID, 'path': pin['path'], 'sha256': pin['sha256']}]
    schema = node['parameters']['output_schema']['properties']
    assert schema['entries']['items']['enum'] == [e['id'] for e in FICTIONAL['entries']]
    assert schema['request_sha256']['const'] == pin['sha256']
    assert schema['entries']['maxItems'] == schema['terms']['maxItems'] == 4
    document = json.loads(Path(pin['path']).read_text())
    assert document['matched_entries'] == ['quuxon', 'missing-glimmer-momentum'] and document['role'] == q.ROLE
    for bad in [{'adapter': 'arbitrary'}, {'model': ' '}, {'max_output_tokens': 10}]:
        with pytest.raises(ValueError):
            q.graph_spec(pin, **{'graph_id': 'g', 'model': 'm', 'reasoning_effort': 'low', 'vocabulary': path,
                                 'roles': ROLES, **bad})


@pytest.mark.parametrize('roles', [{'aliases': {}, 'roles': {}},
                                   {'aliases': {}, 'roles': {q.ROLE: {'card': {'id': q.ROLE, 'protocol': []}}}},
                                   {'aliases': {}, 'roles': {q.ROLE: {'card': {'id': q.ROLE, 'protocol': [' ']}}}}])
def test_the_governed_call_needs_a_registered_card_protocol(tmp_path, roles):
    with pytest.raises(ValueError, match='role_card_unavailable'):
        q.request_document(QUERY, vocabulary=vocabulary(tmp_path), roles=roles)


def test_request_documents_are_fresh_exact_projections(tmp_path):
    base, path, pin, _ = prepared(tmp_path)
    with pytest.raises(FileExistsError):
        q.write_request(pin['path'], q.request_document(QUERY, vocabulary=path, roles=ROLES), vocabulary=path, roles=ROLES)
    forged = q.request_document(QUERY, vocabulary=path, roles=ROLES)
    forged['entries'][0]['forms'].append('injected form')
    with pytest.raises(ValueError, match='projection'):
        q.write_request(base / 'forged.json', forged, vocabulary=path, roles=ROLES)
    with pytest.raises(ValueError, match='allowance'):
        q.request_document(QUERY, vocabulary=path, roles=ROLES, limits={'max_model_entries': 0, 'max_model_terms': 0})


def test_admitted_choice_adds_closed_entries_and_source_bound_terms_only(tmp_path, inert, monkeypatch):
    base, path, pin, spec = prepared(tmp_path)
    run = inert(base / 'graph', spec, reply(pin, ['quuxon', 'zorp-boson'],
                                            ['glimmer tail', 'vanishing glow', 'see: elsewhere', 'quuxon']))
    assert run['complete'] and run['usage']['calls'] == 1
    def no_call(*args, **kwargs):
        raise AssertionError('admission and expansion only read the recorded call')
    monkeypatch.setattr(graph, 'execute', no_call)
    monkeypatch.setattr(agent_host.AgentHost, 'execute', no_call)
    result = q.expand(QUERY, vocabulary=path, roles=ROLES, governed={'request': pin, 'graph_root': str(base / 'graph')},
                      known_tokens=q.source_vocabulary(['a glimmer tail was seen near a quuxon']))
    model = result['model']
    assert model['status'] == 'admitted' and model['entries'] == ['quuxon', 'zorp-boson']
    known = sorted(q.source_vocabulary(['a glimmer tail was seen near a quuxon']))
    assert result['source_vocabulary'] == {'sha256': hashlib.sha256(q._canonical(known)).hexdigest(), 'tokens': len(known)}
    receipt = Path(model['receipt']['path'])
    assert hashlib.sha256(receipt.read_bytes()).hexdigest() == model['receipt']['sha256']
    origins = {(t['text'], t['origin']) for t in result['terms']}
    assert {("Zorp'", 'model_entry'), ('heavy zorp boson', 'model_entry'), ('glimmer tail', 'model_term')} <= origins
    assert {(None, 'already_expanded'), ('vanishing glow', 'not_in_source_vocabulary'),
            ('see: elsewhere', 'invalid_term'), ('quuxon', 'present_in_query')} <= reasons(result)
    without = q.expand(QUERY, vocabulary=path, roles=ROLES, governed={'request': pin, 'graph_root': str(base / 'graph')})
    assert ('glimmer tail', 'no_source_vocabulary') in reasons(without)
    assert not any(t['origin'] == 'model_term' for t in without['terms'])


def test_model_caps_from_the_caller_bound_an_admitted_choice(tmp_path, inert):
    base, path, pin, spec = prepared(tmp_path)
    inert(base / 'graph', spec, reply(pin, ['zorp-boson', 'florp-region'], ['glimmer tail', 'glimmer edge']))
    result = q.expand(QUERY, vocabulary=path, roles=ROLES, governed={'request': pin, 'graph_root': str(base / 'graph')},
                      known_tokens={'glimmer', 'tail', 'edge'}, limits={'max_model_entries': 1, 'max_model_terms': 1})
    assert {('florp-region', 'model_entry_cap')} <= {(o['entry'], o['reason']) for o in result['omitted']}
    assert ('glimmer edge', 'model_term_cap') in reasons(result)


def test_unexecuted_failed_or_out_of_schema_calls_are_refused_and_expansion_stands(tmp_path, inert):
    base, path, pin, spec = prepared(tmp_path)
    graph.create(base / 'idle', spec)
    assert q.admit(pin, base / 'idle', vocabulary=path, roles=ROLES) == {
        'status': 'refused', 'reason': 'graph_result_unavailable', 'request_sha256': pin['sha256']}
    assert q.admit(pin, base / 'absent', vocabulary=path, roles=ROLES)['reason'] == 'graph_result_unavailable'
    run = inert(base / 'graph', spec, reply(pin, ['not-an-entry']))
    assert not run['complete']
    result = q.expand(QUERY, vocabulary=path, roles=ROLES, governed={'request': pin, 'graph_root': str(base / 'graph')})
    assert result['model']['reason'] == 'graph_result_unavailable'
    assert result['terms'] == q.expand(QUERY, vocabulary=path)['terms']


def test_altered_graph_request_vocabulary_or_query_is_refused(tmp_path, inert):
    base, path, pin, spec = prepared(tmp_path)
    altered = deepcopy(spec)
    altered['nodes'][0]['parameters']['instructions'] += ' Also answer the question.'
    inert(base / 'altered', altered, reply(pin, ['zorp-boson']))
    assert q.admit(pin, base / 'altered', vocabulary=path, roles=ROLES)['reason'] == 'graph_spec_mismatch'
    inert(base / 'graph', spec, reply(pin, ['zorp-boson']))
    assert q.admit(pin, base / 'graph', vocabulary=path, roles=ROLES)['status'] == 'admitted'
    changed = deepcopy(FICTIONAL)
    changed['entries'][0]['forms'].append({'text': 'glimmer thrust'})
    assert q.admit(pin, base / 'graph', vocabulary=vocabulary(base, changed, 'changed.json'),
                   roles=ROLES)['reason'] == 'vocabulary_changed'
    drifted = deepcopy(ROLES)
    drifted['roles'][q.ROLE]['card']['protocol'] = PROTOCOL + ['Also answer the question.']
    assert q.admit(pin, base / 'graph', vocabulary=path, roles=drifted)['reason'] == 'graph_spec_mismatch'
    assert q.admit(pin, base / 'graph', vocabulary=path,
                   roles={'aliases': {}, 'roles': {}})['reason'] == 'role_card_unavailable'
    other = q.expand('a different quuxon question', vocabulary=path,
                     roles=ROLES, governed={'request': pin, 'graph_root': str(base / 'graph')})
    assert other['model'] == {'status': 'refused', 'reason': 'other_query', 'request_sha256': pin['sha256']}
    assert not any(t['origin'].startswith('model') for t in other['terms'])
    Path(pin['path']).write_text(Path(pin['path']).read_text().replace('quuxon production', 'quuxon productions'))
    assert q.admit(pin, base / 'graph', vocabulary=path, roles=ROLES)['reason'] == 'request_pin_mismatch'
    assert q.admit({'path': pin['path']}, base / 'graph', vocabulary=path, roles=ROLES)['reason'] == 'invalid_request_pin'
    with pytest.raises(ValueError, match='exactly a request pin'):
        q.expand(QUERY, vocabulary=path, roles=ROLES, governed={'request': pin})


def test_cli_prints_the_deterministic_expansion(tmp_path, capsys):
    path = vocabulary(tmp_path)
    assert q.main(['--query', 'quuxon', '--vocabulary', path, '--limits', '{"max_terms": 1}']) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == q.expand('quuxon', vocabulary=path, limits={'max_terms': 1})
    assert q.main(['--query', 'quuxon', '--vocabulary', path, '--limits', '{"max_terms": 99}']) == 2
