"""The paired retrieval benchmark runner over fictional corpora, questions and fake deterministic models.

No real model, network or scientific job runs; the pinned-model path is the
existing skip-guarded qualification test. The fakes differ in dimension and token
window, so each arm builds its own index from the same located corpus.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ravel.workflow import literature_benchmark as bench, literature_cli, literature_provider as contract
from test_literature_serving import PAPERS, make_corpus


class FakeEmbedding:
    """Deterministic word-statistics vectors of its own dimension; passages split to its own window."""

    def __init__(self, name, dimension, window):
        self.dimension, self.token_window = dimension, window
        self.identity = {'name': name, 'dimension': dimension, 'window': window}

    def passage_tokens(self, texts):
        return [len(text.split()) + 2 for text in texts]

    def _vector(self, text):
        words = text.lower().split()
        return [1.0 + (sum(len(w) for w in words) * (i + 1)) % 7 for i in range(self.dimension)]

    def embed_documents(self, texts):
        if any(n > self.token_window for n in self.passage_tokens(texts)):
            raise ValueError('passage exceeds the fake window')
        return [self._vector(t) for t in texts]

    def embed_query(self, text):
        return self._vector(text)


class FakeReranker:
    identity = {'name': 'fake-reranker'}

    def __init__(self):
        self.calls = 0

    def score(self, query, texts):
        self.calls += 1
        wanted = set(query.lower().split())
        return [float(len(wanted & set(t.lower().split()))) for t in texts]


MODELS = {'fake-small': (3, 64), 'fake-wide': (5, 15)}
PAPERS_LONG = deepcopy(PAPERS)
PAPERS_LONG['birch']['lines'][1] = ('Birch method repeats the counting rule across every sampled grove before the '
                                    'tally is compared with the earlier calm season record.')
QUESTIONS = {'items': [{'id': 'Q1', 'text': 'Which alder rate is reported?', 'stratum': 'fictional'},
                       {'id': 'Q2', 'text': 'Which counting rule does the birch method use?'},
                       {'id': 'Q3', 'text': 'cedar dry conditions rate'}]}


@pytest.fixture
def world(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setenv('RAVEL_STATE_DIR', str(base / 'state'))
    source = base / 'corpus'
    source.mkdir()
    corpus = base / 'corpus.json'
    corpus.write_text(json.dumps(make_corpus(source, PAPERS_LONG)))
    questions = base / 'questions.json'
    questions.write_text(json.dumps(QUESTIONS))
    rerankers = {}

    def adapters(model_id):
        dimension, window = MODELS[model_id]
        rerankers[model_id] = FakeReranker()
        return FakeEmbedding(model_id, dimension, window), rerankers[model_id]
    ticks = iter(range(1, 10 ** 6))
    return dict(base=base, source=source, corpus=corpus, questions=questions, adapters=adapters,
                rerankers=rerankers, clock=lambda: next(ticks) * 0.01)


def lines(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def test_each_model_gets_its_own_index_and_a_registered_run_file(world):
    manifest = bench.run(questions=world['questions'], out=world['base'] / 'bench', base_dir=world['source'],
                         model_ids=['fake-small', 'fake-wide'], corpus=world['corpus'], adapters=world['adapters'],
                         default_model='fake-small', replicates=2, clock=world['clock'])
    small, wide = manifest['models']['fake-small'], manifest['models']['fake-wide']
    assert small['arm'] == 'R-rerank' and wide['arm'] == 'R-rerank@fake-wide'
    assert (small['index']['dimensions'], wide['index']['dimensions']) == (3, 5)
    # The narrow window splits units the wide one keeps whole; both serve exact located excerpts.
    assert wide['index']['units'] > small['index']['units']
    assert small['index']['manifest_sha256'] != wide['index']['manifest_sha256']
    for model, entry in manifest['models'].items():
        rows = lines(entry['run_file']['path'])
        raw = Path(entry['run_file']['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry['run_file']['sha256'] and len(rows) == 6
        assert [(r['question_id'], r['replicate']) for r in rows] == [(q, n) for n in (1, 2) for q in ('Q1', 'Q2', 'Q3')]
        assert [r['cache'] for r in rows] == ['cold'] + ['warm'] * 5
        for row in rows:
            assert set(row) == {'arm', 'question_id', 'replicate', 'status', 'latency_seconds', 'cache', 'usage',
                                'envelope'}
            assert row['status'] == 'ok' and row['arm'] == entry['arm'] and row['usage']['model_calls'] == 0
            envelope = row['envelope']
            assert envelope['operation'] == 'search' and envelope['provider_id'] == 'local-hybrid'
            assert envelope['index']['manifest_sha256'] == entry['index']['manifest_sha256']
            assert 'elapsed_seconds' not in envelope['usage'] and len(envelope['results']) <= 20
            assert all(r['scores']['reranker'] is not None for r in envelope['results'])
        assert world['rerankers'][model].calls >= 6
        latency = entry['latency']
        assert latency['cold_seconds'] > 0 and latency['warm_count'] == 5 and latency['warm_p95_seconds'] > 0
        assert entry['build_seconds'] > 0 and entry['status'] == {'ok': 6}
        assert entry['embedding'] == {'name': model, 'dimension': MODELS[model][0], 'window': MODELS[model][1]}
    first = lines(small['run_file']['path'])[0]['envelope']['results'][0]
    assert first['document_id'] == 'paper:alder' and 'alder' in first['text'].lower()
    question_raw = world['questions'].read_bytes()
    assert manifest['questions'] == {'path': str(world['questions'].resolve()), 'questions': 3,
                                     'sha256': hashlib.sha256(question_raw).hexdigest(), 'size': len(question_raw)}
    assert manifest['corpus']['sha256'] == hashlib.sha256(world['corpus'].read_bytes()).hexdigest()
    assert set(manifest['code']) == set(bench.CODE) and manifest['settings']['reranker'] == 'on'
    assert json.loads((world['base'] / 'bench' / 'manifest.json').read_text()) == manifest


def test_identical_inputs_reproduce_the_located_envelopes(world):
    runs = [bench.run(questions=world['questions'], out=world['base'] / name, base_dir=world['source'],
                      model_ids=['fake-wide'], corpus=world['corpus'], adapters=world['adapters'],
                      default_model='fake-small', clock=world['clock']) for name in ('first', 'second')]
    # The ranked located evidence reproduces; receipts and the policy view digest are bound to each run.
    results = [[r['envelope']['results'] for r in lines(m['models']['fake-wide']['run_file']['path'])] for m in runs]
    assert results[0] == results[1] and all(results[0])
    assert runs[0]['models']['fake-wide']['index'] == runs[1]['models']['fake-wide']['index']


@pytest.mark.parametrize('item', [{'id': 'Q1', 'text': 'q', 'answer': 'secret'}, {'id': 'Q1', 'text': ' '},
                                  {'text': 'no id'}, {'id': 'Q1', 'text': 'q', 'gold': []}])
def test_question_files_carry_only_ids_and_texts(world, item):
    world['questions'].write_text(json.dumps({'items': [item]}))
    with pytest.raises(ValueError, match='question'):
        bench.run(questions=world['questions'], out=world['base'] / 'bench', base_dir=world['source'],
                  model_ids=['fake-small'], corpus=world['corpus'], adapters=world['adapters'])
    assert not (world['base'] / 'bench').exists()


def test_inputs_are_explicit_and_outputs_fresh(world):
    common = dict(questions=world['questions'], base_dir=world['source'], adapters=world['adapters'])
    with pytest.raises(ValueError, match='one admitted build record or one compiled corpus'):
        bench.run(out=world['base'] / 'a', model_ids=['fake-small'], **common)
    with pytest.raises(ValueError, match='distinct'):
        bench.run(out=world['base'] / 'b', model_ids=['fake-small', 'fake-small'], corpus=world['corpus'], **common)
    (world['base'] / 'c').mkdir()
    with pytest.raises(ValueError, match='fresh'):
        bench.run(out=world['base'] / 'c', model_ids=['fake-small'], corpus=world['corpus'], **common)


def test_an_admitted_build_record_compiles_its_located_products(world, tmp_path):
    from ravel.workflow import literature_context as lc
    from test_literature_context import document, request
    base = world['base']
    text = 'A fictional alder survey.\n\nThe alder rate is reported as 3.5 units.\n'
    result = lc.prepare(request(base, [document(base, 'alder-note', text, 'text')]), base / 'located', base_dir=base)
    admission = base / 'admission.json'
    admission.write_text(json.dumps({'products': [result['product']], 'bibliography': []}))
    receipts = {hashlib.sha256(p.read_bytes()).hexdigest(): 'receipt-' + p.name for p in base.rglob('*') if p.is_file()}
    manifest = bench.run(questions=world['questions'], out=base / 'bench', base_dir=base, model_ids=['fake-small'],
                         admission=admission, receipt_ids=receipts, adapters=world['adapters'],
                         default_model='fake-small', clock=world['clock'])
    rows = lines(manifest['models']['fake-small']['run_file']['path'])
    assert manifest['corpus']['kind'] == 'build-admission' and [r['status'] for r in rows] == ['ok'] * 3
    served = [u for r in rows for u in r['envelope']['results']]
    assert served and all(u['document_id'] == 'alder-note' for u in served)
    original = (base / 'alder-note.text').read_bytes()
    for unit in served:
        assert contract.verify_excerpt(unit, original=original)['physics_verified'] is False


def test_the_benchmark_command_is_routed_through_the_literature_command(world, capsys):
    code = literature_cli.main(['benchmark', '--corpus', str(world['corpus']), '--base-dir', str(world['source']),
                                '--questions', str(world['base'] / 'absent.json'), '--out', str(world['base'] / 'o'),
                                '--model', 'fake-small'])
    assert code == 2 and 'ravel literature benchmark' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        literature_cli.main(['benchmark', '--corpus', str(world['corpus'])])


def test_benchmark_checks_origin_lineage_before_loading_or_embedding_models(world):
    calls = []
    def adapters(model_id):
        calls.append(model_id)
        return world['adapters'](model_id)
    with pytest.raises(ValueError, match='excluded origin'):
        bench.run(questions=world['questions'], out=world['base'] / 'denied', base_dir=world['source'],
                  model_ids=['fake-small'], corpus=world['corpus'], adapters=adapters,
                  excluded_origins=[{'kind': 'document', 'value': 'paper:birch'}])
    assert calls == []
    assert not (world['base'] / 'denied' / 'indexes').exists()
