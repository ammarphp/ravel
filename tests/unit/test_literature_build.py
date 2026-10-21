"""Offline storage controls using fictional provider-contract records and deterministic fakes."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from ravel.workflow import literature_build as store
from ravel.workflow import state_io

FIXTURES = Path(__file__).resolve().parents[1] / 'fixtures' / 'literature_provider'
RERANKER = {'name': 'fictional-cross-encoder', 'revision': '1'}


def corpus(count=3):
    cases = json.loads((FIXTURES / 'conformance.json').read_text())
    evidence = deepcopy(cases[0]['candidate']['results'][0])
    paper = deepcopy(next(c for c in cases if c['request']['operation'] == 'get_paper')['candidate']['metadata'][0])
    paper['original']['size'] = 65536
    for field in ('original', 'extraction', 'identifiers', 'quantities', 'classes', 'lineage'):
        evidence[field] = deepcopy(paper[field])
    units = []
    for i in range(count):
        row = deepcopy(evidence)
        row['id'] = f'evidence:amber:{i}'
        row['unit_id'] = f'paragraph:{i}'
        row['text'] = f'Fictional amber measurement {i}.'
        row['excerpt_sha256'] = hashlib.sha256(row['text'].encode()).hexdigest()
        row['location']['byte_end'] = row['location']['byte_start'] + len(row['text'].encode())
        text = paper['title'] + '\n' + ' / '.join(row['location']['section_path']) + '\n' + row['text']
        units.append(dict(evidence=row, indexed_text=text, parent_id=None, section_ids=[]))
    return dict(schema_version=1, units=units, papers=[paper] if count else [], inputs=[])


class Embedder:
    def __init__(self, fail_at=None, result=None):
        self.identity = {'name': 'fictional-embedding', 'revision': '1'}
        self.calls = []
        self.fail_at = fail_at
        self.result = result

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        if len(self.calls) == self.fail_at:
            raise RuntimeError('sensitive provider response')
        if self.result is not None:
            return deepcopy(self.result)
        return [[float(hashlib.sha256(text.encode()).digest()[0] + 1), 1.0] for text in texts]


def build(root, data=None, embedder=None, **kwargs):
    return store.build_index(root, corpus() if data is None else data,
                             embedder=Embedder() if embedder is None else embedder,
                             reranker_identity=deepcopy(RERANKER), **kwargs)


def snapshot_path(root, snapshot):
    return root / 'snapshots' / snapshot['manifest']['manifest_sha256']


def test_reproducible_identity_and_bytes_across_directories_and_input_order(tmp_path):
    data = corpus()
    reordered = deepcopy(data)
    reordered['units'].reverse()
    reordered = dict(reversed(list(reordered.items())))
    first = build(tmp_path / 'a', data)
    second = build(tmp_path / 'b', reordered)
    assert first == second
    for name in ('manifest.json', 'corpus.json', 'vectors.json'):
        assert (snapshot_path(tmp_path / 'a', first) / name).read_bytes() == (snapshot_path(tmp_path / 'b', second) / name).read_bytes()
    assert store.load_index(tmp_path / 'a') == first
    assert store.load_index(tmp_path / 'a', first['manifest']['manifest_sha256']) == first


def test_existing_snapshot_needs_no_inference_and_results_are_detached(tmp_path):
    first = build(tmp_path)
    embedder = Embedder(fail_at=1)
    assert build(tmp_path, embedder=embedder) == first
    assert embedder.calls == []
    first['vectors'][0][0] = -123
    assert store.load_index(tmp_path)['vectors'][0][0] != -123
    loaded = store.load_index(tmp_path)
    checked = store.validate_snapshot(loaded)
    checked['manifest']['embedding']['name'] = 'changed'
    assert loaded['manifest']['embedding']['name'] == 'fictional-embedding'


def test_failed_build_preserves_current_and_resumes_completed_batches(tmp_path):
    initial = build(tmp_path, corpus(1))
    current = (tmp_path / 'current.json').read_bytes()
    failed = Embedder(fail_at=2)
    with pytest.raises(ValueError, match='adapter failed') as error:
        build(tmp_path, corpus(4), failed, batch_size=1)
    assert 'sensitive' not in str(error.value)
    assert (tmp_path / 'current.json').read_bytes() == current
    assert store.load_index(tmp_path) == initial
    resumed = Embedder()
    final = build(tmp_path, corpus(4), resumed, resume=True, batch_size=1)
    assert len(resumed.calls) == 3
    assert failed.calls[0] not in resumed.calls
    assert len(final['vectors']) == 4


def test_publication_discards_its_redundant_resume_journal(tmp_path, monkeypatch):
    # A published snapshot holds every vector; a retained journal duplicates them.
    with pytest.raises(ValueError, match='adapter failed'):
        build(tmp_path, corpus(4), Embedder(fail_at=2), batch_size=1)
    assert list((tmp_path / 'staging').glob('*/progress.json'))
    final = build(tmp_path, corpus(4), resume=True, batch_size=1)
    assert list((tmp_path / 'staging').iterdir()) == []
    assert store.load_index(tmp_path) == final
    # Interrupted after the snapshot rename, before the pointer: the journal
    # survives, and the next matching build discards it without inference.
    write = store._write
    def interrupted(path, value):
        if Path(path).name == 'current.json':
            raise OSError('fictional interruption')
        return write(path, value)
    monkeypatch.setattr(store, '_write', interrupted)
    with pytest.raises(OSError):
        build(tmp_path, corpus(2), batch_size=1)
    monkeypatch.setattr(store, '_write', write)
    assert list((tmp_path / 'staging').glob('*/progress.json'))
    embedder = Embedder()
    recovered = build(tmp_path, corpus(2), embedder, resume=True)
    assert embedder.calls == [] and store.load_index(tmp_path) == recovered
    assert list((tmp_path / 'staging').iterdir()) == []


def test_update_reuses_unchanged_records_and_preserves_old_snapshot(tmp_path):
    first = build(tmp_path)
    updated = corpus(4)
    del updated['units'][1]
    embedder = Embedder()
    second = store.update_index(tmp_path, updated, embedder=embedder, reranker_identity=RERANKER)
    assert len(embedder.calls) == 1 and len(embedder.calls[0]) == 1
    assert store.load_index(tmp_path, first['manifest']['manifest_sha256']) == first
    assert second['manifest']['unit_count'] == 3
    assert {u['evidence']['unit_id'] for u in second['corpus']['units']} == {'paragraph:0', 'paragraph:2', 'paragraph:3'}


def test_update_does_not_reuse_changed_evidence_or_embedding_identity(tmp_path):
    build(tmp_path)
    data = corpus()
    row = data['units'][0]['evidence']
    row['location']['line_start'] += 1
    row['location']['line_end'] += 1
    embedder = Embedder()
    store.update_index(tmp_path, data, embedder=embedder, reranker_identity=RERANKER)
    assert len(embedder.calls[0]) == 1
    embedder = Embedder()
    embedder.identity['revision'] = '2'
    store.update_index(tmp_path, data, embedder=embedder, reranker_identity=RERANKER)
    assert len(embedder.calls[0]) == 3


@pytest.mark.parametrize('bad', [[], [[1.0]], [[0.0, 0.0]], [[float('nan'), 1]],
                                    [[float('inf'), 1]], [[True, 1]], [[1, 2], [1]],
                                    [[1, 2], [3, 4], [5, 6]]])
def test_invalid_embeddings_never_publish(tmp_path, bad):
    # Two-unit request distinguishes count errors from dimensional errors.
    with pytest.raises(ValueError):
        build(tmp_path, corpus(2), Embedder(result=bad))
    assert not (tmp_path / 'current.json').exists()


def test_cross_batch_dimension_mismatch_never_publishes(tmp_path):
    class Changing(Embedder):
        def embed_documents(self, texts):
            self.calls.append(texts)
            return [[1.0] * len(self.calls) for _ in texts]
    with pytest.raises(ValueError):
        build(tmp_path, embedder=Changing(), batch_size=1)
    assert not (tmp_path / 'current.json').exists()


def test_empty_corpus_has_zero_dimensions_and_no_inference(tmp_path):
    embedder = Embedder(fail_at=1)
    result = build(tmp_path, corpus(0), embedder)
    assert result['manifest']['dimensions'] == 0
    assert result['vectors'] == [] and embedder.calls == []
    assert store.load_index(tmp_path) == result


@pytest.mark.parametrize('name', ['manifest.json', 'corpus.json', 'vectors.json'])
def test_tampered_snapshot_refused(tmp_path, name):
    result = build(tmp_path)
    path = snapshot_path(tmp_path, result) / name
    value = json.loads(path.read_text())
    if name == 'manifest.json':
        value['unit_count'] += 1
    elif name == 'corpus.json':
        value['units'][0]['indexed_text'] += ' tampered'
    else:
        value[0][0] += 1
    state_io.atomic_json(path, value)
    with pytest.raises(ValueError):
        store.load_index(tmp_path)


@pytest.mark.parametrize('mutation', ['unknown', 'zero', 'duplicate', 'key', 'dimensions', 'finite-vector'])
def test_corrupt_resume_journal_refused(tmp_path, mutation):
    with pytest.raises(ValueError):
        build(tmp_path, embedder=Embedder(fail_at=2), batch_size=1)
    path = next((tmp_path / 'staging').glob('*/progress.json'))
    journal = json.loads(path.read_text())
    if mutation == 'unknown':
        journal['embeddings'][0]['key'] = 'f' * 64
    elif mutation == 'zero':
        journal['embeddings'][0]['vector'] = [0.0, 0.0]
    elif mutation == 'duplicate':
        journal['embeddings'] *= 2
    elif mutation == 'key':
        journal['key'] = 'e' * 64
    elif mutation == 'finite-vector':
        journal['embeddings'][0]['vector'][0] += 0.5
    else:
        # Complete second valid key, then inject incompatible dimensions.
        keys = [store._cache_key(Embedder().identity, u) for u in corpus()['units']]
        other = next(k for k in keys if k != journal['embeddings'][0]['key'])
        journal['embeddings'].append({'key': other, 'vector': [1.0]})
    if mutation != 'finite-vector':
        journal['journal_sha256'] = store._hash({
            'key': journal['key'], 'embeddings': journal['embeddings']})
    state_io.atomic_json(path, journal)
    embedder = Embedder()
    with pytest.raises(ValueError):
        build(tmp_path, embedder=embedder, resume=True)
    assert embedder.calls == []
    assert not (tmp_path / 'current.json').exists()


@pytest.mark.parametrize('bad', ['../escape', '/absolute', 'A' * 64, 'x', None, 42])
def test_malformed_current_pointer_refused(tmp_path, bad):
    state_io.atomic_json(tmp_path / 'current.json', {'id': bad})
    with pytest.raises(ValueError):
        store.load_index(tmp_path)


@pytest.mark.parametrize('raw', ['{"id":"x","id":"y"}', '{"id":NaN}', '{"id":1e999}'])
def test_duplicate_and_nonfinite_json_refused(tmp_path, raw):
    (tmp_path / 'current.json').write_text(raw)
    with pytest.raises(ValueError):
        store.load_index(tmp_path)


def test_identity_detached_and_mid_build_mutation_refused(tmp_path):
    class Mutating(Embedder):
        def embed_documents(self, texts):
            result = super().embed_documents(texts)
            self.identity['revision'] = 'changed'
            return result
    with pytest.raises(ValueError, match='identity changed'):
        build(tmp_path, embedder=Mutating())
    assert not (tmp_path / 'current.json').exists()


@pytest.mark.parametrize('location', ['root', 'snapshots', 'snapshot', 'manifest', 'current', 'staging', 'lock'])
def test_symlinked_storage_refused(tmp_path, location):
    root = tmp_path / 'store'
    result = build(root)
    paths = {'root': root, 'snapshots': root / 'snapshots',
             'snapshot': snapshot_path(root, result),
             'manifest': snapshot_path(root, result) / 'manifest.json',
             'current': root / 'current.json', 'staging': root / 'staging',
             'lock': root / 'build.lock'}
    path = paths[location]
    target = tmp_path / 'relocated'
    path.rename(target)
    path.symlink_to(target, target_is_directory=target.is_dir())
    with pytest.raises(ValueError, match='symlink'):
        store.load_index(root)


def test_concurrent_writers_serialize_and_share_completed_snapshot(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    entered, release, second_started = Event(), Event(), Event()

    class Paused(Embedder):
        def embed_documents(self, texts):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('fixture coordination timeout')
            return super().embed_documents(texts)

    first_embedder, second_embedder = Paused(), Embedder()
    def second():
        second_started.set()
        return build(tmp_path, embedder=second_embedder)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(build, tmp_path, None, first_embedder)
        assert entered.wait(5)
        later = pool.submit(second)
        assert second_started.wait(5)
        release.set()
        a, b = first.result(timeout=10), later.result(timeout=10)
    assert a == b
    assert len(first_embedder.calls) == 1
    assert second_embedder.calls == []
    assert store.load_index(tmp_path) == a


@pytest.mark.parametrize('bad', [{}, {'value': float('nan')}, {'value': float('inf')}, {'value': object()}, []])
def test_invalid_adapter_identities_refused(tmp_path, bad):
    embedder = Embedder()
    embedder.identity = bad
    with pytest.raises(ValueError):
        build(tmp_path, embedder=embedder)
    with pytest.raises(ValueError):
        store.build_index(tmp_path, corpus(), embedder=Embedder(), reranker_identity=bad)
    assert not (tmp_path / 'current.json').exists()


@pytest.mark.parametrize('bad', [[[0.0, 0.0], [1, 2]], [[float('nan'), 1], [1, 2]],
                                    [[float('inf'), 1], [1, 2]], [[True, 1], [1, 2]],
                                    [[1.7e308, 1.7e308], [1, 2]]])
def test_invalid_vector_values_at_correct_count_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        build(tmp_path, corpus(2), Embedder(result=bad))
    assert not (tmp_path / 'current.json').exists()


def test_json_distinct_identities_never_alias(tmp_path):
    first_embedder = Embedder()
    first_embedder.identity['revision'] = True
    first = build(tmp_path, embedder=first_embedder)
    second_embedder = Embedder()
    second_embedder.identity['revision'] = 1
    second = build(tmp_path, embedder=second_embedder)
    assert second_embedder.calls
    assert first['manifest']['manifest_sha256'] != second['manifest']['manifest_sha256']


def test_symlinked_storage_ancestor_refused(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    alias = tmp_path / 'alias'
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        build(alias / 'nested-store')
    assert not (real / 'nested-store').exists()


# ---- excluded origins: lineage-based exclusion before any derived artifact is written

def _origin_corpus(root, papers=None):
    from test_literature_serving import PAPERS, make_corpus
    return make_corpus(root, PAPERS if papers is None else papers)


def _origin_build(root, corpus, origins):
    from test_literature_serving import Embedder, Reranker
    return store.build_index(root, corpus, embedder=Embedder(), reranker_identity=Reranker().identity,
                             excluded_origins=origins)


@pytest.mark.parametrize('origin', [{'kind': 'document', 'value': 'paper:birch'},
                                    {'kind': 'document', 'value': 'fictional-preprint-birch'},
                                    {'kind': 'path', 'value': 'sources/birch.txt'},
                                    {'kind': 'path', 'value': 'sources'}])
def test_a_corpus_descending_from_an_excluded_origin_is_refused_before_any_write(tmp_path, origin):
    corpus = _origin_corpus(tmp_path / 'corpus')
    embedded = []
    from test_literature_serving import Embedder
    class Counting(Embedder):
        def embed_documents(self, texts):
            embedded.append(len(texts))
            return super().embed_documents(texts)
    with pytest.raises(ValueError, match='descend from an excluded origin'):
        store.build_index(tmp_path / 'index', corpus, embedder=Counting(),
                          reranker_identity={'name': 'r', 'revision': '1'}, excluded_origins=[origin])
    assert embedded == [] and not (tmp_path / 'index' / 'current.json').exists()
    assert not any((tmp_path / 'index' / 'snapshots').iterdir()) if (tmp_path / 'index' / 'snapshots').exists() else True


def test_derived_rows_carry_the_exclusion_of_their_source(tmp_path):
    corpus = _origin_corpus(tmp_path / 'corpus')
    # The acquisition record behind a generated lineage row is the excluded origin; its paper is refused.
    cedar = next(p for p in corpus['papers'] if p['document_id'] == 'paper:cedar')
    generated = next(d for d in cedar['lineage'] if d['kind'] == 'generated')
    with pytest.raises(ValueError, match='1 row\\(s\\) descend|row\\(s\\) descend'):
        _origin_build(tmp_path / 'index', corpus, [{'kind': 'pin', 'value': generated['pin']['sha256']}])


def test_a_derived_row_without_ancestry_is_refused_when_origins_are_configured(tmp_path):
    corpus = _origin_corpus(tmp_path / 'corpus', {})
    descriptor = {'pin': {'path': 'derived/summary.json', 'sha256': 'c' * 64, 'size': 10,
                          'receipt_id': 'receipt:summary'},
                  'identifiers': {}, 'quantities': [], 'classes': [], 'kind': 'generated'}
    corpus['papers'].append({'id': 'record:orphan', 'document_id': 'paper:orphan', 'version': None,
                             'title': 'Fictional derived summary', 'original': None, 'extraction': None,
                             'extraction_reason': 'No source is recorded.', 'identifiers': {},
                             'quantities': [], 'classes': [], 'lineage': [descriptor],
                             'acquisition_status': 'missing', 'extraction_issues': [], 'physics_verified': False,
                             'execution_authorized': False, 'reason': 'Derived without a recorded source.'})
    with pytest.raises(ValueError, match='1 derived row\\(s\\) name no ancestry'):
        _origin_build(tmp_path / 'index', corpus, [{'kind': 'document', 'value': 'paper:elsewhere'}])
    # Without a configured set the same corpus builds as before: the rule applies to configured exclusion.
    assert _origin_build(tmp_path / 'plain', corpus, None)['manifest']['unit_count'] == 0


def test_the_manifest_records_the_excluded_origin_set(tmp_path):
    corpus = _origin_corpus(tmp_path / 'corpus', {k: v for k, v in __import__('test_literature_serving').PAPERS.items()
                                                  if k == 'alder'})
    plain = _origin_build(tmp_path / 'index', corpus, None)['manifest']
    assert 'excluded_origins_sha256' not in plain
    first = _origin_build(tmp_path / 'index', corpus, [{'kind': 'document', 'value': 'paper:elm'}])['manifest']
    second = _origin_build(tmp_path / 'index', corpus, [{'kind': 'document', 'value': 'paper:oak'}])['manifest']
    assert first['excluded_origins_sha256'] != second['excluded_origins_sha256']
    assert len({plain['manifest_sha256'], first['manifest_sha256'], second['manifest_sha256']}) == 3
    again = _origin_build(tmp_path / 'index', corpus, [{'kind': 'document', 'value': 'paper:elm'}])['manifest']
    assert again == first
    for bad in ([{'kind': 'paper', 'value': 'x'}], [{'kind': 'pin', 'value': 'not-a-digest'}], 'paper:elm'):
        with pytest.raises(ValueError):
            _origin_build(tmp_path / 'bad', corpus, bad)


@pytest.mark.parametrize('value', ['', '/', '../sources', 'sources/../derived', './sources', 'sources//nested'])
def test_excluded_origin_paths_have_one_unambiguous_relative_spelling(value):
    from ravel.workflow.literature_index import normalize_excluded_origins
    with pytest.raises(ValueError):
        normalize_excluded_origins([{'kind': 'path', 'value': value}])


def test_transformed_inputs_without_source_lineage_fail_closed(tmp_path):
    corpus = _origin_corpus(tmp_path / 'corpus', {})
    corpus['inputs'] = [{'pin': {'path': 'summaries/derived.json', 'sha256': 'd' * 64,
                                'size': 10, 'receipt_id': 'receipt:derived'}, 'identifiers': {},
                         'quantities': [], 'classes': [], 'kind': 'generated'}]
    with pytest.raises(ValueError, match='ancestry'):
        _origin_build(tmp_path / 'index', corpus, [{'kind': 'document', 'value': 'paper:withheld'}])
    assert not (tmp_path / 'index').exists()


def test_direct_build_honors_the_trusted_installation_origin_policy(tmp_path, monkeypatch):
    import json
    from ravel.workflow import literature_settings as settings
    config = tmp_path / 'settings.json'
    config.write_text(json.dumps({'schema_version': 1, 'kind': settings.SETTINGS_KIND,
                                  'retrieval': {'excluded_origins': [
                                      {'kind': 'document', 'value': 'paper:birch'}]}}))
    monkeypatch.setenv(settings.SETTINGS_ENV, str(config))
    with pytest.raises(ValueError, match='excluded origin'):
        _origin_build(tmp_path / 'index', _origin_corpus(tmp_path / 'corpus'), None)
    assert not (tmp_path / 'index').exists()
