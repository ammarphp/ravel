"""Pinned local literature models: custody, deterministic CPU inference and qualification.

Fictional tiny ONNX models and vocabularies stand in for the pinned weights; an
independent NumPy oracle supplies their expected outputs. The pinned models are
exercised only when an installation is named by RAVEL_LITERATURE_MODELS.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace
import urllib.request

import numpy as np
import pytest

from ravel.workflow import literature_models as lm

onnx = pytest.importorskip('onnx')
pytest.importorskip('onnxruntime')
from onnx import TensorProto, helper, numpy_helper  # noqa: E402

VOCAB = ['[PAD]', '[UNK]', '[CLS]', '[SEP]', 'zorvel', 'quenth', 'brillow', 'tamsik', 'olvane',
         'pexil', 'durnap', 'wistle', 'kelvra', 'mondo', 'fasp', 'yorrel', 'instruct', 'find']
DIM = 6
PREFIX = 'instruct find '
RNG = np.random.default_rng(20261017)
EMB = RNG.normal(size=(len(VOCAB), DIM)).astype(np.float32)
TYPES = RNG.normal(size=(2, DIM)).astype(np.float32)
WEIGHTS = RNG.normal(size=len(VOCAB)).astype(np.float32)


# ---------------------------------------------------------------- fictional artifacts

def embedding_onnx(output='last_hidden_state', dim=DIM):
    """tanh(E[ids] + T[types] + masked mean over the sequence): CLS sees every real token."""
    ints = [helper.make_tensor_value_info(n, TensorProto.INT64, ['batch', 'seq'])
            for n in ('input_ids', 'attention_mask', 'token_type_ids')]
    out = helper.make_tensor_value_info(output, TensorProto.FLOAT, ['batch', 'seq', dim])
    inits = [numpy_helper.from_array(EMB[:, :dim], 'E'), numpy_helper.from_array(TYPES[:, :dim], 'T'),
             numpy_helper.from_array(np.array([2], np.int64), 'ax2'),
             numpy_helper.from_array(np.array([1], np.int64), 'ax1')]
    nodes = [helper.make_node('Gather', ['E', 'input_ids'], ['h0']),
             helper.make_node('Gather', ['T', 'token_type_ids'], ['t']),
             helper.make_node('Add', ['h0', 't'], ['h']),
             helper.make_node('Cast', ['attention_mask'], ['mf'], to=TensorProto.FLOAT),
             helper.make_node('Unsqueeze', ['mf', 'ax2'], ['m3']),
             helper.make_node('Mul', ['h', 'm3'], ['hm']),
             helper.make_node('ReduceSum', ['hm', 'ax1'], ['s'], keepdims=1),
             helper.make_node('ReduceSum', ['m3', 'ax1'], ['c'], keepdims=1),
             helper.make_node('Div', ['s', 'c'], ['ctx']),
             helper.make_node('Add', ['h', 'ctx'], ['pre']),
             helper.make_node('Tanh', ['pre'], [output])]
    graph = helper.make_graph(nodes, 'fictional_embedder', ints, [out], inits)
    return helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=8).SerializeToString()


def reranker_onnx(with_types=True):
    """logit = sum over real tokens of w[id] * (1 + type)."""
    names = ('input_ids', 'attention_mask') + (('token_type_ids',) if with_types else ())
    ints = [helper.make_tensor_value_info(n, TensorProto.INT64, ['batch', 'seq']) for n in names]
    out = helper.make_tensor_value_info('logits', TensorProto.FLOAT, ['batch', 1])
    inits = [numpy_helper.from_array(WEIGHTS, 'W'), numpy_helper.from_array(np.array([1], np.int64), 'ax1'),
             numpy_helper.from_array(np.array(1.0, np.float32), 'one')]
    nodes = [helper.make_node('Gather', ['W', 'input_ids'], ['w']),
             helper.make_node('Cast', ['attention_mask'], ['mf'], to=TensorProto.FLOAT),
             helper.make_node('Mul', ['w', 'mf'], ['wm'])]
    if with_types:
        nodes += [helper.make_node('Cast', ['token_type_ids'], ['tf'], to=TensorProto.FLOAT),
                  helper.make_node('Add', ['tf', 'one'], ['tp']),
                  helper.make_node('Mul', ['wm', 'tp'], ['prod'])]
    else:
        nodes += [helper.make_node('Identity', ['wm'], ['prod'])]
    nodes += [helper.make_node('ReduceSum', ['prod', 'ax1'], ['logits'], keepdims=1)]
    graph = helper.make_graph(nodes, 'fictional_reranker', ints, [out], inits)
    return helper.make_model(graph, opset_imports=[helper.make_opsetid('', 17)], ir_version=8).SerializeToString()


class FakeTokenizer:
    """Whitespace WordPiece stand-in with BERT special-token layout and only-second truncation."""

    def __init__(self, vocab, max_len=None):
        self.vocab, self.max_len = vocab, max_len

    def token_to_id(self, token):
        return self.vocab.get(token)

    def _ids(self, text):
        return [self.vocab.get(w, 1) for w in text.lower().split()]

    def encode(self, first, second=None, add_special_tokens=True):
        a = self._ids(first)
        if not add_special_tokens:
            return SimpleNamespace(ids=a, type_ids=[0] * len(a))
        ids, types = [2] + a + [3], [0] * (len(a) + 2)
        if second is not None:
            b = self._ids(second)
            if self.max_len is not None and len(ids) + len(b) + 1 > self.max_len:
                room = self.max_len - len(ids) - 1
                if room < 1:
                    raise ValueError('second sequence not long enough to be truncated')
                b = b[:room]
            ids, types = ids + b + [3], types + [1] * (len(b) + 1)
        return SimpleNamespace(ids=ids, type_ids=types)


def fake_factory(text, model):
    vocab = json.loads(text)['vocab']
    truncating = model['tokenizer']['max_tokens'] if model['role'] == 'reranker' else None
    return FakeTokenizer(vocab), FakeTokenizer(vocab, truncating), 'fake-0'


def oracle_embed(ids, types):
    h = EMB[ids] + TYPES[types]
    v = np.tanh(h[0] + h.mean(0)).astype(np.float64)
    return (v / np.linalg.norm(v)).astype(np.float32)


def oracle_score(ids, types):
    return float(np.sum(WEIGHTS[ids].astype(np.float64) * (1 + np.asarray(types))))


def store(root, data):
    digest = hashlib.sha256(data).hexdigest()
    path = Path(root) / 'sha256' / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {'size': len(data), 'sha256': digest}


EMB_PROBES = [('query', 'zorvel quenth'), ('passage', 'brillow tamsik olvane pexil'), ('passage', 'durnap')]
RR_PROBES = [('zorvel quenth', 'brillow tamsik'), ('zorvel quenth', 'olvane unknownword pexil durnap')]


def make_installation(root, *, max_tokens=32, with_types=True, embedding_bytes=None, reranker_bytes=None):
    """Write fictional files into ``root`` and return a validated catalogue pinning them."""
    vocab = {w: i for i, w in enumerate(VOCAB)}
    tok_text = json.dumps({'vocab': vocab}).encode()
    notice = store(root, b'Fictional licence text for test models.\n')
    card = b'---\nlicense: mit\n---\nA fictional model card.\n'
    tokenizer = FakeTokenizer(vocab)

    def entry(model_id, role, model_bytes, inputs, output):
        files = {'model': {'path': 'onnx/model.onnx', **store(root, model_bytes)},
                 'tokenizer': {'path': 'tokenizer.json', **store(root, tok_text)},
                 'model_card': {'path': 'README.md', **store(root, card)}}
        return {'id': model_id, 'role': role, 'host': 'https://huggingface.co',
                'repository': 'fictional-org/' + model_id, 'revision': 'a' * 40,
                'license': {'spdx': 'MIT', 'declared_by': {'file': 'README.md', 'value': 'license: mit'},
                            'notice': {'url': 'https://example.org/LICENSE', **notice}},
                'files': files, 'onnx': {'inputs': inputs, 'output': output},
                'tokenizer': {'max_tokens': max_tokens, 'pad_token': '[PAD]', 'pad_id': 0}}

    emb = entry('fictional-embedder', 'embedding', embedding_bytes or embedding_onnx(),
                ['input_ids', 'attention_mask', 'token_type_ids'], 'last_hidden_state')
    emb['embedding'] = {'pooling': 'cls', 'normalize': 'l2', 'dimension': DIM,
                        'query_prefix': PREFIX, 'passage_prefix': ''}
    probes = []
    for kind, text in EMB_PROBES:
        enc = tokenizer.encode((PREFIX if kind == 'query' else '') + text)
        vec = oracle_embed(enc.ids, enc.type_ids).astype('<f4')
        probes.append({'kind': kind, 'text': text, 'token_ids': enc.ids,
                       'vector_f32le_b64': base64.b64encode(vec.tobytes()).decode()})
    emb['qualification'] = {'reference': {'producer': 'NumPy oracle of the fictional graph'},
                            'tolerance': {'max_abs': 1e-5, 'min_cosine': 0.9999}, 'probes': probes}
    inputs = ['input_ids', 'attention_mask'] + (['token_type_ids'] if with_types else [])
    rr = entry('fictional-reranker', 'reranker', reranker_bytes or reranker_onnx(with_types), inputs, 'logits')
    rr['reranker'] = {'score': 'logit', 'truncation': 'only_second', 'max_query_tokens': 8}
    rr_probes = []
    for query, passage in RR_PROBES:
        enc = tokenizer.encode(query, passage)
        types = enc.type_ids if with_types else [0] * len(enc.ids)
        rr_probes.append({'query': query, 'passage': passage, 'token_ids': enc.ids,
                          'score': oracle_score(enc.ids, types)})
    rr['qualification'] = {'reference': {'producer': 'NumPy oracle of the fictional graph'},
                           'tolerance': {'max_abs': 1e-4}, 'probes': rr_probes}
    doc = {'schema_version': 1, 'runtime': {'provider': 'CPUExecutionProvider', 'threads': 1,
                                            'batch_size': 4, 'pad_multiple': 16},
           'defaults': {'embedding': 'fictional-embedder', 'reranker': 'fictional-reranker'},
           'models': {'fictional-embedder': emb, 'fictional-reranker': rr}}
    return lm.validate_catalogue(doc)


@pytest.fixture
def installed(tmp_path):
    root = tmp_path / 'models'
    return root, make_installation(root)


def embedder(root, doc, **kw):
    return lm.Embedder(root=root, doc=doc, tokenizer_factory=fake_factory, **kw)


def reranker(root, doc, **kw):
    return lm.Reranker(root=root, doc=doc, tokenizer_factory=fake_factory, **kw)


# ---------------------------------------------------------------- catalogue

def test_packaged_catalogue_pins_every_file_licence_and_role_default():
    doc = lm.catalogue()
    assert set(doc['defaults']) == set(lm.ROLES)
    for model_id, model in doc['models'].items():
        assert model['host'].startswith('https://') and len(model['revision']) == 40
        assert model['license']['spdx'] in lm.LICENCES
        assert {'model', 'tokenizer', 'model_card'} <= set(model['files'])
        assert model['license']['declared_by']['file'] == model['files']['model_card']['path']
        assert model['qualification']['probes'], model_id
    default = lm.model_entry(role='embedding')
    assert default['embedding']['pooling'] == 'cls' and default['embedding']['normalize'] == 'l2'
    assert lm.model_entry(role='reranker')['role'] == 'reranker'
    assert doc['runtime']['provider'] == 'CPUExecutionProvider'


def _mutate(doc, path, value):
    target = doc
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value


E = ('models', 'fictional-embedder')
R = ('models', 'fictional-reranker')


@pytest.mark.parametrize('path,value', [
    (E + ('files', 'model', 'sha256'), 'f' * 63),
    (E + ('files', 'model', 'size'), 0),
    (E + ('files', 'tokenizer'), KeyError),
    (E + ('files', 'model', 'path'), '../outside.onnx'),
    (E + ('revision',), 'main'),
    (E + ('host',), 'http://huggingface.co'),
    (E + ('license', 'spdx'), 'GPL-3.0-or-later'),
    (E + ('license', 'notice', 'sha256'), None),
    (E + ('license', 'declared_by', 'file'), 'LICENSE-not-pinned'),
    (E + ('license', 'declared_by', 'value'), 'license: apache-2.0'),
    (E + ('onnx', 'inputs'), ['input_ids', 'attention_mask', 'pixel_values']),
    (E + ('embedding', 'pooling'), 'mean'),
    (E + ('embedding', 'normalize'), None),
    (E + ('qualification', 'probes', 0, 'vector_f32le_b64'), base64.b64encode(b'\0' * 8).decode()),
    (E + ('qualification', 'tolerance', 'max_abs'), 2.0),
    (E + ('tokenizer', 'max_tokens'), 24),
    (R + ('reranker', 'truncation'), 'longest_first'),
    (R + ('reranker', 'max_query_tokens'), 17),
    (R + ('qualification', 'probes', 0, 'score'), True),
    (R + ('qualification', 'probes', 0, 'score'), float('nan')),
    (E + ('qualification', 'probes', 0, 'vector_f32le_b64'),
     base64.b64encode(np.full(DIM, np.inf, '<f4').tobytes()).decode()),
    (('defaults', 'reranker'), 'fictional-embedder'),
    (('runtime', 'threads'), 0),
    (('runtime', 'pad_multiple'), 3),
])
def test_validator_rejects_unpinned_or_unadmitted_entries(tmp_path, path, value):
    doc = make_installation(tmp_path)
    _mutate(doc, path, value)
    with pytest.raises(lm.ModelError, match='invalid model catalogue'):
        lm.validate_catalogue(doc)


def test_model_entry_resolves_defaults_and_refuses_unknown_or_wrong_role(installed):
    _root, doc = installed
    assert lm.model_entry(role='reranker', doc=doc)['id'] == 'fictional-reranker'
    with pytest.raises(lm.ModelError):
        lm.model_entry('fictional-embedder', role='reranker', doc=doc)
    with pytest.raises(lm.ModelError):
        lm.model_entry('absent-model', doc=doc)
    with pytest.raises(lm.ModelError):
        lm.model_entry(doc=doc)


def test_default_root_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(lm.ROOT_ENV, str(tmp_path / 'elsewhere'))
    assert lm.default_root() == tmp_path / 'elsewhere'
    monkeypatch.delenv(lm.ROOT_ENV)
    assert lm.default_root().name == 'literature-models'


# ---------------------------------------------------------------- custody

class Opener:
    def __init__(self, blobs):
        self.blobs, self.calls = blobs, []

    def __call__(self, url, timeout):
        import io
        self.calls.append(url)
        if url not in self.blobs:
            raise OSError('not served: ' + url)
        return io.BytesIO(self.blobs[url])


def _served(source_root, doc):
    """The fictional files of ``doc`` keyed by the URL prefetch must use."""
    blobs = {}
    for model in doc['models'].values():
        for _name, url, pin in lm._pins(model):
            blobs[url] = (Path(source_root) / 'sha256' / pin['sha256']).read_bytes()
    return blobs


def test_prefetch_fetches_only_on_request_verifies_and_is_idempotent(tmp_path):
    doc = make_installation(tmp_path / 'source')
    opener = Opener(_served(tmp_path / 'source', doc))
    root = tmp_path / 'models'
    assert lm.inspect(root=root, doc=doc)['models'][0]['complete'] is False
    report = lm.prefetch(root=root, opener=opener, doc=doc)
    assert {m['model_id'] for m in report['models']} == {'fictional-embedder', 'fictional-reranker'}
    pins = [(url, pin['sha256']) for m in doc['models'].values() for _n, url, pin in lm._pins(m)]
    expected = {url for url, _sha in pins}
    # Content-addressed: a file shared by two models is requested once.
    assert set(report['network_requests']) <= expected
    assert len(report['network_requests']) == len({sha for _url, sha in pins})
    assert all(urls.startswith('https://huggingface.co/fictional-org/') and '/resolve/' + 'a' * 40 + '/' in urls
               for urls in expected if 'example.org' not in urls)
    assert all(m['complete'] for m in lm.inspect(root=root, doc=doc)['models'])
    again = lm.prefetch(root=root, opener=opener, doc=doc)
    assert again['network_requests'] == []
    with pytest.raises(lm.ModelError, match='list of model ids'):
        lm.prefetch('fictional-embedder', root=root, opener=opener, doc=doc)


def test_prefetch_of_an_altered_download_quarantines_it_and_installs_nothing(tmp_path):
    doc = make_installation(tmp_path / 'source')
    blobs = _served(tmp_path / 'source', doc)
    url = next(u for u in blobs if u.endswith('onnx/model.onnx'))
    blobs[url] = blobs[url][:-1] + b'\x00'
    root = tmp_path / 'models'
    with pytest.raises(lm.ModelError, match='prefetch of fictional-embedder model failed'):
        lm.prefetch(['fictional-embedder'], root=root, opener=Opener(blobs), doc=doc)
    status = lm.verify('fictional-embedder', root=root, doc=doc)
    assert not status['complete']
    assert {r['name']: r['status'] for r in status['files']}['model'] == 'missing'
    assert list((root / 'quarantine').iterdir())


def test_prefetch_refuses_a_model_card_that_does_not_declare_the_catalogued_licence(tmp_path):
    source = tmp_path / 'source'
    doc = make_installation(source)
    files = doc['models']['fictional-reranker']['files']
    files['model_card'] = {'path': 'README.md', **store(source, b'---\nlicense: other\n---\nlicense: mit\n')}
    doc = lm.validate_catalogue(doc)
    root = tmp_path / 'models'
    opener = Opener(_served(source, doc))
    lm.prefetch(['fictional-embedder'], root=root, opener=opener, doc=doc)
    with pytest.raises(lm.ModelError, match='fictional-reranker model card does not declare license: mit'):
        lm.prefetch(['fictional-reranker'], root=root, opener=opener, doc=doc)
    # The pinned bytes are now present, yet neither the status nor loading accepts them.
    status = {m['model_id']: m for m in lm.inspect(root=root, doc=doc)['models']}
    assert status['fictional-embedder']['complete'] and status['fictional-embedder']['licence_declared']
    assert all(r['status'] == 'ok' for r in status['fictional-reranker']['files'])
    assert status['fictional-reranker']['licence_declared'] is False
    assert status['fictional-reranker']['complete'] is False
    with pytest.raises(lm.ModelError, match='does not declare'):
        reranker(root, doc)
    assert lm.verify('fictional-reranker', root=tmp_path / 'empty', doc=doc)['licence_declared'] is None


def test_altered_installed_file_is_reported_and_never_loaded_or_repaired(installed):
    root, doc = installed
    pin = doc['models']['fictional-embedder']['files']['model']
    path = root / 'sha256' / pin['sha256']
    path.write_bytes(path.read_bytes() + b'\x00')
    status = lm.verify('fictional-embedder', root=root, doc=doc)
    assert {r['name']: r['status'] for r in status['files']}['model'] == 'altered'
    with pytest.raises(lm.ModelError, match='differs from its pin'):
        embedder(root, doc)
    assert path.exists() and not (root / 'quarantine').exists()


def test_missing_installation_names_the_explicit_prefetch(tmp_path):
    doc = make_installation(tmp_path / 'source')
    with pytest.raises(lm.ModelError, match='prefetch'):
        embedder(tmp_path / 'empty', doc)


def test_loading_and_inference_never_use_the_network(installed, monkeypatch):
    root, doc = installed

    def refuse(*args, **kwargs):
        raise AssertionError('network access during load or inference')
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    embedder(root, doc).embed_passages(['zorvel quenth'])
    reranker(root, doc).score('zorvel', ['quenth brillow'])


def test_onnx_signature_that_differs_from_the_catalogue_is_refused(tmp_path):
    root = tmp_path / 'models'
    doc = make_installation(root, embedding_bytes=embedding_onnx(output='hidden'))
    with pytest.raises(lm.ModelError, match='ONNX output differs'):
        embedder(root, doc)
    root2 = tmp_path / 'models2'
    doc = make_installation(root2, embedding_bytes=embedding_onnx(dim=DIM - 1))
    with pytest.raises(lm.ModelError, match='ONNX output differs'):
        embedder(root2, doc)
    root3 = tmp_path / 'models3'
    doc = make_installation(root3, reranker_bytes=reranker_onnx(with_types=False))
    with pytest.raises(lm.ModelError, match='ONNX inputs differ'):
        reranker(root3, doc)


# ---------------------------------------------------------------- inference

def test_embeddings_are_cls_pooled_unit_vectors_matching_the_oracle(installed):
    root, doc = installed
    e = embedder(root, doc)
    texts = ['zorvel quenth brillow', 'tamsik', 'olvane pexil durnap wistle kelvra mondo']
    out = e.embed_passages(texts)
    assert out.vectors.dtype == np.float32 and out.vectors.shape == (3, DIM)
    assert not out.vectors.flags.writeable
    tok = FakeTokenizer({w: i for i, w in enumerate(VOCAB)})
    for text, vec in zip(texts, out.vectors):
        enc = tok.encode(text)
        np.testing.assert_allclose(vec, oracle_embed(enc.ids, enc.type_ids), atol=2e-6)
        assert abs(float(np.linalg.norm(vec.astype(np.float64))) - 1) < 1e-6
    assert out.token_counts == (5, 3, 8)
    assert out.identity_sha256 == e.identity()['identity_sha256']


def test_query_prefix_is_applied_to_queries_only(installed):
    root, doc = installed
    e = embedder(root, doc)
    assert e.token_counts(['zorvel'], kind='query') == [e.token_counts(['zorvel'])[0] + 2]
    query = e.embed_queries(['zorvel']).vectors[0]
    assert np.array_equal(query, e.embed_passages([PREFIX + 'zorvel']).vectors[0])
    assert not np.array_equal(query, e.embed_passages(['zorvel']).vectors[0])


def test_outputs_are_repeatable_and_batch_effects_stay_at_rounding_level(installed):
    root, doc = installed
    words = VOCAB[4:]
    texts = [' '.join(words[(i * 3) % len(words):][: 1 + (i * 5) % 11] or words[:2]) for i in range(23)]
    base = embedder(root, doc, batch_size=1).embed_passages(texts).vectors
    for kw in ({'batch_size': 7}, {'batch_size': 32}, {'batch_size': 4, 'threads': 2}):
        e = embedder(root, doc, **kw)
        first = e.embed_passages(texts).vectors
        assert np.array_equal(first, e.embed_passages(texts).vectors)
        # Companions and thread partitions may move the last bits on some CPU kernels, never more.
        np.testing.assert_allclose(first, base, rtol=0, atol=1e-6)
    order = list(reversed(range(len(texts))))
    shuffled = embedder(root, doc, batch_size=5).embed_passages([texts[i] for i in order]).vectors
    np.testing.assert_allclose(shuffled, base[order], rtol=0, atol=1e-6)


def test_batches_keep_only_the_first_position_of_each_output(installed):
    # A retained view would keep every batch's full hidden-state array alive until the end.
    root, doc = installed
    e = embedder(root, doc, batch_size=2)
    rows = e._run(e._encode(['zorvel quenth brillow tamsik olvane'] * 5, 'passage'))
    assert all(row.shape == (DIM,) and row.base is None for row in rows)
    r = reranker(root, doc, batch_size=2)
    rows = r._run(r._encode('zorvel', ['quenth brillow'] * 3)[0])
    assert all(row.shape == () and row.base is None for row in rows)


def test_overlong_embedding_input_is_refused_never_truncated(installed):
    root, doc = installed
    e = embedder(root, doc)
    long_text = ' '.join(['zorvel'] * 31)
    assert e.token_counts([long_text]) == [33]
    with pytest.raises(lm.ModelError, match='exceed the 32-token window.*split'):
        e.embed_passages(['quenth', long_text])
    assert e.embed_passages([' '.join(['zorvel'] * 30)]).token_counts == (32,)


@pytest.mark.parametrize('bad', [[], [''], ['   '], [None], ['x' * (lm.MAX_TEXT_BYTES + 1)], 'zorvel'])
def test_invalid_text_inputs_are_refused(installed, bad):
    root, doc = installed
    with pytest.raises(lm.ModelError):
        embedder(root, doc).embed_passages(bad)


@pytest.mark.parametrize('kw', [{'threads': 0}, {'threads': lm.MAX_THREADS + 1}, {'batch_size': 0},
                                {'batch_size': True}])
def test_runtime_settings_are_bounded(installed, kw):
    root, doc = installed
    with pytest.raises(lm.ModelError):
        embedder(root, doc, **kw)


def test_reranker_scores_match_the_oracle_and_rank_orders_ties_by_key(installed):
    root, doc = installed
    r = reranker(root, doc)
    passages = ['brillow tamsik', 'olvane', 'tamsik brillow', 'kelvra mondo fasp']
    scores = r.score('zorvel quenth', passages)
    tok = FakeTokenizer({w: i for i, w in enumerate(VOCAB)})
    for passage, got in zip(passages, scores.scores):
        enc = tok.encode('zorvel quenth', passage)
        assert got == pytest.approx(oracle_score(enc.ids, enc.type_ids), abs=1e-5)
    assert scores.truncated == (False,) * 4
    ranked = r.rank('zorvel quenth', [('unit-b', passages[0]), ('unit-a', passages[0]), ('unit-c', passages[1])])
    assert [row['key'] for row in ranked][:2] == ['unit-a', 'unit-b']
    assert ranked[0]['score'] == ranked[1]['score']
    with pytest.raises(lm.ModelError):
        r.rank('zorvel', [('same', 'quenth'), ('same', 'olvane')])


def test_reranker_truncates_only_with_an_explicit_flag_and_refuses_long_queries(installed):
    root, doc = installed
    r = reranker(root, doc)
    long_passage = ' '.join(['brillow'] * 40)
    out = r.score('zorvel', ['quenth', long_passage])
    assert out.truncated == (False, True)
    assert out.token_counts == (5, 32)
    with pytest.raises(lm.ModelError, match='query exceeds 8 tokens'):
        r.score(' '.join(['zorvel'] * 9), ['quenth'])


def test_reranker_without_token_types_uses_its_declared_signature(tmp_path):
    root = tmp_path / 'models'
    doc = make_installation(root, with_types=False)
    r = reranker(root, doc)
    tok = FakeTokenizer({w: i for i, w in enumerate(VOCAB)})
    enc = tok.encode('zorvel', 'quenth brillow')
    assert r.score('zorvel', ['quenth brillow']).scores[0] == pytest.approx(
        oracle_score(enc.ids, [0] * len(enc.ids)), abs=1e-5)
    assert lm.qualify(r)['passed']


def test_identity_separates_model_semantics_from_runtime(tmp_path):
    root = tmp_path / 'models'
    doc = make_installation(root)
    one = embedder(root, doc, threads=1).identity()
    two = embedder(root, doc, threads=2, batch_size=8).identity()
    assert one['identity_sha256'] == two['identity_sha256']
    assert (one['runtime']['threads'], two['runtime']['threads']) == (1, 2)
    assert one['runtime']['tokenizers'] == 'fake-0' and one['runtime']['pad_multiple'] == 16
    changed = copy.deepcopy(doc)
    changed['models']['fictional-embedder']['embedding']['query_prefix'] = 'find '
    assert embedder(root, lm.validate_catalogue(changed)).identity()['identity_sha256'] != one['identity_sha256']


# ---------------------------------------------------------------- qualification

def test_qualify_passes_against_an_independent_reference(installed):
    root, doc = installed
    for model in (embedder(root, doc, batch_size=2), reranker(root, doc)):
        report = lm.qualify(model)
        assert report['passed'] and report['token_ids_equal'] and report['repeatable']
        assert report['batch_within_tolerance'] and isinstance(report['batch_invariant'], bool)
        assert report['measured']['max_abs'] <= report['tolerance']['max_abs']
        assert report['measured']['batch_max_abs'] <= 1e-6


def test_qualify_reports_measured_failures_and_never_adjusts_the_reference(installed):
    root, doc = installed
    bad = copy.deepcopy(doc)
    probe = bad['models']['fictional-embedder']['qualification']['probes'][1]
    vec = np.frombuffer(base64.b64decode(probe['vector_f32le_b64']), '<f4').copy()
    vec[0] += 1e-3
    probe['vector_f32le_b64'] = base64.b64encode(vec.astype('<f4').tobytes()).decode()
    bad['models']['fictional-embedder']['qualification']['probes'][0]['token_ids'][-2] = 1
    bad['models']['fictional-reranker']['qualification']['probes'][1]['score'] += 0.01
    bad = lm.validate_catalogue(bad)
    before = copy.deepcopy(bad)
    emb = lm.qualify(embedder(root, bad))
    assert not emb['passed'] and emb['token_mismatches'] == [0] and not emb['within_tolerance']
    assert emb['measured']['max_abs'] == pytest.approx(1e-3, rel=0.05)
    rr = lm.qualify(reranker(root, bad))
    assert not rr['passed'] and rr['token_ids_equal'] and rr['measured']['max_abs'] == pytest.approx(0.01, rel=0.05)
    assert bad == before


def test_measure_rerank_latency_reports_wall_times_and_conditions(installed):
    root, doc = installed
    report = lm.measure_rerank_latency(reranker(root, doc), 'zorvel', ['quenth brillow'] * 50, repeats=3)
    assert report['passages'] == 50 and len(report['seconds']) == 3
    assert report['median_seconds'] >= 0 and report['runtime']['provider'] == 'CPUExecutionProvider'
    assert report['pair_tokens'] == {'median': 6, 'max': 6}
    with pytest.raises(lm.ModelError):
        lm.measure_rerank_latency(reranker(root, doc), 'zorvel', ['quenth'], repeats=0)


# ---------------------------------------------------------------- the tokenizers library

def test_default_factory_disables_file_padding_and_truncation(tmp_path, monkeypatch):
    tokenizers = pytest.importorskip('tokenizers')

    def refuse(*args, **kwargs):
        raise AssertionError('network access while building a tokenizer')
    monkeypatch.setattr(urllib.request, 'urlopen', refuse)
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    from tokenizers import models, normalizers, pre_tokenizers, processors
    vocab = {w: i for i, w in enumerate(VOCAB)}
    tok = tokenizers.Tokenizer(models.WordPiece(vocab, unk_token='[UNK]'))
    tok.normalizer = normalizers.BertNormalizer(lowercase=True)
    tok.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tok.post_processor = processors.BertProcessing(('[SEP]', 3), ('[CLS]', 2))
    tok.enable_padding(length=24, pad_id=0, pad_token='[PAD]')
    tok.enable_truncation(4)
    text = tok.to_str()
    model = make_installation(tmp_path)['models']['fictional-reranker']
    plain, truncating, version = lm._tokenizers(text, model)
    assert version == tokenizers.__version__
    assert plain.encode('Zorvel QUENTH brillow tamsik olvane').ids == [2, 4, 5, 6, 7, 8, 3]
    pair = plain.encode('zorvel', ' '.join(['brillow'] * 40))
    assert len(pair.ids) == 44 and pair.type_ids[-1] == 1
    cut = truncating.encode('zorvel', ' '.join(['brillow'] * 40))
    assert len(cut.ids) == 32 and cut.ids[:3] == [2, 4, 3] and cut.ids[-1] == 3


# ---------------------------------------------------------------- pinned models, when installed

def _installed_models():
    root = os.environ.get(lm.ROOT_ENV)
    if not root:
        return []
    return [m for m in sorted(lm.catalogue()['models']) if lm.verify(m, root=root)['complete']]


@pytest.mark.parametrize('model_id', _installed_models() or [pytest.param(None, marks=pytest.mark.skip(
    reason='no pinned literature model installation is named by ' + lm.ROOT_ENV))])
def test_installed_pinned_models_qualify_on_this_platform(model_id):
    pytest.importorskip('tokenizers')
    entry = lm.model_entry(model_id)
    cls = lm.Embedder if entry['role'] == 'embedding' else lm.Reranker
    report = lm.qualify(cls(model_id, root=os.environ[lm.ROOT_ENV]))
    assert report['token_ids_equal'], report['token_mismatches']
    assert report['within_tolerance'] and report['batch_within_tolerance'], report['measured']
    assert report['repeatable'] and report['passed']


# ---------------------------------------------------------------- explicit provisioning and token windows

WORDS = ['zorvel', 'quenth', 'brillow', 'tamsik', 'olvane', 'pexil', 'durnap', 'wistle', 'kelvra', 'mondo',
         'fasp', 'yorrel']


def words(n):
    return ' '.join(WORDS[i % len(WORDS)] for i in range(n))


class CountingFetcher:
    """The installer fetcher, counted; only an explicit prefetch may construct it."""
    made, real = [], None

    def __init__(self, *args, **kwargs):
        CountingFetcher.made.append(args)
        self._inner = CountingFetcher.real(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._inner, name)


@pytest.fixture
def counted(monkeypatch):
    from ravel.setup import fetch
    CountingFetcher.made, CountingFetcher.real = [], fetch.Fetcher
    monkeypatch.setattr(fetch, 'Fetcher', CountingFetcher)
    return CountingFetcher.made


def adapters(root, doc, **kw):
    emb, rr = embedder(root, doc, **kw), reranker(root, doc, **kw)
    return lm.index_models(emb, rr, embedding_qualification=lm.qualify(emb), reranker_qualification=lm.qualify(rr))


def run_main(capsys, argv, **kw):
    code = lm.main(argv, **kw)
    out = capsys.readouterr()
    return code, (json.loads(out.out) if out.out.strip() else None), out.err


def test_models_cli_is_offline_except_explicit_prefetch(tmp_path, capsys, counted):
    doc = make_installation(tmp_path / 'source')
    opener, root = Opener(_served(tmp_path / 'source', doc)), tmp_path / 'models'
    code, report, _ = run_main(capsys, ['inspect', '--root', str(root)], doc=doc)
    assert code == 1 and not any(m['complete'] for m in report['models'])
    code, report, err = run_main(capsys, ['qualify', '--root', str(root)], doc=doc, tokenizer_factory=fake_factory)
    assert code == 2 and report is None and 'prefetch' in err
    assert counted == [] and opener.calls == []
    code, report, _ = run_main(capsys, ['prefetch', '--root', str(root)], doc=doc, opener=opener)
    assert code == 0 and len(counted) == 1 and opener.calls
    assert {m['model_id'] for m in report['models']} == {'fictional-embedder', 'fictional-reranker'}
    fetched = list(opener.calls)
    code, report, _ = run_main(capsys, ['inspect', '--root', str(root)], doc=doc)
    assert code == 0 and all(m['complete'] for m in report['models'])
    code, report, _ = run_main(capsys, ['qualify', 'fictional-reranker', '--root', str(root), '--threads', '1'],
                               doc=doc, tokenizer_factory=fake_factory)
    assert code == 0 and [r['model_id'] for r in report] == ['fictional-reranker'] and report[0]['passed']
    code, report, _ = run_main(capsys, ['qualify', '--root', str(root)], doc=doc, tokenizer_factory=fake_factory)
    assert code == 0 and sorted(r['model_id'] for r in report) == ['fictional-embedder', 'fictional-reranker']
    # An altered installed asset fails inspection and qualification; nothing repairs or downloads it.
    model = lm._stored(root, doc['models']['fictional-embedder']['files']['model'])
    model.write_bytes(model.read_bytes() + b'altered')
    code, report, _ = run_main(capsys, ['inspect', '--root', str(root)], doc=doc)
    assert code == 1 and {r['name']: r['status'] for r in report['models'][0]['files']}['model'] == 'altered'
    code, _, err = run_main(capsys, ['qualify', '--root', str(root)], doc=doc, tokenizer_factory=fake_factory)
    assert code == 2 and 'differs from its pin' in err
    assert len(counted) == 1 and opener.calls == fetched


def test_models_cli_exits_one_on_a_failed_qualification_and_routes_from_the_literature_command(
        installed, capsys, monkeypatch, counted):
    root, doc = installed
    monkeypatch.setattr(lm, 'qualify', lambda loaded: {'model_id': loaded.model['id'], 'passed': False})
    code, report, _ = run_main(capsys, ['qualify', '--root', str(root)], doc=doc, tokenizer_factory=fake_factory)
    assert code == 1 and [r['passed'] for r in report] == [False, False]
    from ravel.workflow import literature_cli
    assert literature_cli.main(['models', 'inspect', '--root', str(root / 'packaged')]) == 1
    assert set(json.loads(capsys.readouterr().out)['defaults']) == set(lm.ROLES) and counted == []


def test_index_adapters_bind_qualified_assets_and_refuse_pair_overflow(installed, counted):
    root, doc = installed
    emb, rr = adapters(root, doc)
    assert emb.token_window == 23 and emb.query_window == 8
    assert lm.pair_limits(doc['models']['fictional-embedder'], doc['models']['fictional-reranker']) == {
        'passage_tokens': 23, 'query_tokens': 8}
    for identity in (emb.identity, rr.identity):
        assert {'identity_sha256', 'tokenizer_sha256', 'runtime', 'qualification_sha256', 'pair_limits'} <= set(identity)
    # Boundary lengths: exactly at the limit is served, one more token is refused, never truncated.
    assert emb.passage_tokens([words(21)]) == [23] and len(emb.embed_documents([words(21)])) == 1
    with pytest.raises(lm.ModelError, match='pair limit'):
        emb.embed_documents([words(22)])
    assert len(emb.embed_query(words(8))) == DIM
    with pytest.raises(lm.ModelError, match='8-token limit'):
        emb.embed_query(words(9))
    assert len(rr.score(words(8), [words(21)])) == 1
    with pytest.raises(lm.ModelError, match='never truncate'):
        rr.score(words(8), [words(22)])
    with pytest.raises(lm.ModelError, match='not qualified'):
        lm.IndexEmbedder(embedder(root, doc), doc['models']['fictional-reranker'],
                         qualification={'passed': False})
    with pytest.raises(lm.ModelError, match='another model or runtime'):
        lm.IndexEmbedder(embedder(root, doc, threads=2), doc['models']['fictional-reranker'],
                         qualification=lm.qualify(embedder(root, doc)))
    assert counted == []


def split_corpus(tmp_path, texts):
    from test_literature_graph_retrieval import make_corpus
    return make_corpus(texts)


def test_build_splits_units_by_tokenizer_counts_with_exact_membership(installed, tmp_path, counted):
    from ravel.workflow import literature_build as build, literature_index as index
    from ravel.workflow import literature_provider as contract
    root, doc = installed
    emb, rr = adapters(root, doc)
    # Title and heading take 4 words, the special tokens 2: 17 excerpt words fill the 23-token window.
    texts = {'a': [words(17)], 'b': [words(18)], 'c': [words(40)]}
    data, raws = split_corpus(tmp_path, texts)
    snapshot = build.build_index(tmp_path / 'index', data, embedder=emb, reranker_identity=rr.identity)
    units = snapshot['corpus']['units']
    pieces = {}
    for unit in units:
        row = unit['evidence']
        pieces.setdefault(row['id'].split('#')[0], []).append(row)
        assert emb.passage_tokens([unit['indexed_text']])[0] <= emb.token_window
        assert contract.verify_excerpt(row, original=raws[row['document_id']])['physics_verified'] is False
    assert {k: len(v) for k, v in pieces.items()} == {'evidence:a:1': 1, 'evidence:b:1': 2, 'evidence:c:1': 3}
    for name, paragraphs in texts.items():
        rows = sorted(pieces['evidence:%s:1' % name], key=lambda r: int(('#0' + r['id'].partition('#')[2])[1:] or 0))
        assert ''.join(r['text'] for r in rows) == paragraphs[0]
        assert rows[0]['unit_id'] == 'paragraph:1' and [len(r['text'].split()) for r in rows][:1] == [min(17, len(paragraphs[0].split()))]
    assert snapshot['manifest']['embedding'] == emb.identity and snapshot['manifest']['reranker'] == rr.identity
    provider = index.HybridLiteratureProvider(snapshot, embedder=emb, reranker=rr, cursor_key=b'k' * 32)
    view = contract.SourceView(policy_sha256='2' * 64, run_id='run:fictional', node_id='node:reader',
                               role='reader', attempt=1, permits=lambda _: True)
    request = {'schema_version': 1, 'operation': 'search', 'request_id': 'request:models',
               'budgets': {'max_tokens': 262144, 'max_bytes': 262144, 'max_seconds': 10.0, 'max_expansions': 200},
               'args': {'query': words(3), 'top_k': 3, 'mode': 'flat', 'document_scope': [], 'filters': {}}}
    assert provider.search(request, view=view)['results']
    # A changed runtime or asset makes the index stale; nothing is fetched to repair it.
    stale_emb, stale_rr = adapters(root, doc, threads=2)
    with pytest.raises(ValueError, match='differs from index'):
        index.HybridLiteratureProvider(snapshot, embedder=stale_emb, reranker=stale_rr, cursor_key=b'k' * 32)
    tokenizer = lm._stored(root, doc['models']['fictional-embedder']['files']['tokenizer'])
    tokenizer.write_bytes(tokenizer.read_bytes() + b' ')
    with pytest.raises(lm.ModelError, match='differs from its pin'):
        adapters(root, doc)
    assert counted == []


def test_split_boundaries_with_a_deterministic_counter(tmp_path):
    from ravel.workflow import literature_index as index
    count = lambda texts: [len(t.split()) + 2 for t in texts]
    data, _ = split_corpus(tmp_path, {'a': [words(5)]})
    # Prefix of 4 words and 2 specials: limit 6 leaves no room for the excerpt, 7 leaves one word per piece.
    with pytest.raises(ValueError, match='leave no room'):
        index.split_units(data, count=count, limit=6)
    one = index.split_units(data, count=count, limit=7)['units']
    assert [u['evidence']['text'] for u in one] == ['zorvel ', 'quenth ', 'brillow ', 'tamsik ', 'olvane']
    assert [u['evidence']['location']['byte_end'] - u['evidence']['location']['byte_start'] for u in one] == [7, 7, 8, 7, 6]
    assert index.split_units(data, count=count, limit=11) == index.validate_corpus(data)
    measured = deepcopy_measurement(data)
    with pytest.raises(ValueError, match='located measurement'):
        index.split_units(measured, count=count, limit=7)


def deepcopy_measurement(data):
    data = copy.deepcopy(data)
    row = data['units'][0]['evidence']
    start = row['location']['byte_start']
    row['measurement'] = {'value': {'value': 'zorvel', 'byte_start': start, 'byte_end': start + 6},
                          'unit': {'value': 'quenth', 'byte_start': start + 7, 'byte_end': start + 13},
                          'conditions': None}
    return data


def test_excluded_roots_refuse_a_build_before_any_embedding(tmp_path, monkeypatch):
    from ravel.workflow import literature_build as build, literature_context, literature_index as index
    data, _ = split_corpus(tmp_path, {'a': [words(3)]})

    class Recording:
        identity = {'name': 'fictional-embedding', 'revision': '1'}
        calls = []

        def embed_documents(self, texts):
            self.calls.append(list(texts))
            return [[1.0, float(len(t))] for t in texts]
    corpus_root = (tmp_path / 'corpus').resolve()
    held = corpus_root / 'held-out'
    common = dict(embedder=Recording(), reranker_identity={'name': 'fictional-reranker'})
    built = build.build_index(tmp_path / 'index', data, excluded_roots=[str(held)], source_root=corpus_root, **common)
    assert built['manifest']['unit_count'] == 1 and len(Recording.calls) == 1
    for roots, source, target, match in (
            ([str(corpus_root / 'sources')], corpus_root, tmp_path / 'index-two', 'corpus member'),
            ([str(corpus_root)], corpus_root, tmp_path / 'index-three', 'corpus root'),
            ([str(tmp_path.resolve() / 'index-four')], corpus_root, tmp_path / 'index-four', 'index'),
            ([str(held)], None, tmp_path / 'index-five', 'absolute corpus source root'),
            (['relative/root'], corpus_root, tmp_path / 'index-six', 'absolute paths')):
        with pytest.raises(ValueError, match=match):
            build.build_index(target, data, excluded_roots=roots, source_root=source, **common)
        assert not target.exists() or not (target / 'current.json').exists()
    assert len(Recording.calls) == 1
    # A located product under an excluded root is refused before it is consumed.
    monkeypatch.setattr(literature_context, 'consume', lambda *a, **k: (_ for _ in ()).throw(AssertionError('read')))
    product = {'path': str(held / 'product.json'), 'sha256': 'f' * 64, 'size': 10}
    with pytest.raises(ValueError, match='excluded root'):
        index.corpus_from_products([product], base_dir=corpus_root, receipt_ids={}, excluded_roots=[str(held)])


# ---------------------------------------------------------------- comparator windows and external weights

class RepeatingTokenizer(FakeTokenizer):
    """Another tokenizer: every word becomes ``repeat`` tokens, so its counts differ from the reranker's."""

    def __init__(self, vocab, repeat):
        super().__init__(vocab)
        self.repeat = repeat

    def _ids(self, text):
        return [i for i in super()._ids(text) for _ in range(self.repeat)]


def comparator_factory(text, model):
    document = json.loads(text)
    if 'repeat' in document:
        tokenizer = RepeatingTokenizer(document['vocab'], document['repeat'])
        return tokenizer, tokenizer, 'fake-0'
    return fake_factory(text, model)


def add_comparator(root, doc, *, dim=4, max_tokens=64, repeat=2, external=False, tmp=None):
    """A fictional comparator embedding model: its own dimension, window and tokenizer."""
    vocab = {w: i for i, w in enumerate(VOCAB)}
    tokenizer = RepeatingTokenizer(vocab, repeat)
    graph = embedding_onnx(dim=dim)
    files = {'tokenizer': {'path': 'tokenizer.json', **store(root, json.dumps({'vocab': vocab, 'repeat': repeat}).encode())},
             'model_card': {'path': 'README.md', **store(root, b'---\nlicense: mit\n---\nA fictional comparator.\n')}}
    onnx_contract = {'inputs': ['input_ids', 'attention_mask', 'token_type_ids'], 'output': 'last_hidden_state'}
    if external:
        model = onnx.load_from_string(graph)
        folder = tmp / 'export'
        folder.mkdir()
        onnx.save_model(model, str(folder / 'model.onnx'), save_as_external_data=True, all_tensors_to_one_file=True,
                        location='model.onnx_data', size_threshold=64)
        files['model'] = {'path': 'onnx/model.onnx', **store(root, (folder / 'model.onnx').read_bytes())}
        files['model_data'] = {'path': 'onnx/model.onnx_data', **store(root, (folder / 'model.onnx_data').read_bytes())}
        onnx_contract['external_data'] = ['model_data']
    else:
        files['model'] = {'path': 'onnx/model.onnx', **store(root, graph)}
    probes = []
    for kind, text in EMB_PROBES:
        enc = tokenizer.encode((PREFIX if kind == 'query' else '') + text)
        h = EMB[enc.ids][:, :dim] + TYPES[enc.type_ids][:, :dim]
        v = np.tanh(h[0] + h.mean(0)).astype(np.float64)
        vec = (v / np.linalg.norm(v)).astype('<f4')
        probes.append({'kind': kind, 'text': text, 'token_ids': enc.ids,
                       'vector_f32le_b64': base64.b64encode(vec.tobytes()).decode()})
    base = doc['models']['fictional-embedder']
    entry = {**copy.deepcopy(base), 'id': 'fictional-comparator', 'repository': 'fictional-org/fictional-comparator',
             'files': files, 'onnx': onnx_contract,
             'tokenizer': {'max_tokens': max_tokens, 'pad_token': '[PAD]', 'pad_id': 0},
             'embedding': {**base['embedding'], 'dimension': dim},
             'qualification': {**copy.deepcopy(base['qualification']), 'probes': probes}}
    return lm.validate_catalogue({**doc, 'models': {**doc['models'], 'fictional-comparator': entry}})


def test_a_comparator_keeps_its_own_dimension_and_window_and_both_pair_bounds(installed, counted):
    from test_literature_graph_retrieval import make_corpus
    from ravel.workflow import literature_build as build, literature_index as index
    root, doc = installed
    doc = add_comparator(root, doc)
    assert doc['defaults']['embedding'] == 'fictional-embedder'
    emb = lm.Embedder('fictional-comparator', root=root, doc=doc, tokenizer_factory=comparator_factory)
    rr = reranker(root, doc)
    assert lm.pair_limits(emb.model, rr.model) == {'passage_tokens': 64, 'query_tokens': 8,
                                                     'reranker_passage_tokens': 23}
    with pytest.raises(lm.ModelError, match='loaded reranker'):
        lm.IndexEmbedder(emb, rr.model, qualification=lm.qualify(emb))
    adapters = lm.index_models(emb, rr, embedding_qualification=lm.qualify(emb), reranker_qualification=lm.qualify(rr))
    embedding, reranking = adapters
    assert embedding.token_window == 64 and embedding.identity['pair_limits']['reranker_passage_tokens'] == 23
    # 21 words: 44 embedding tokens and 23 reranker tokens fit; at 22 the reranker bound binds, not the wider window.
    assert embedding.passage_tokens([words(21)]) == [64] and len(embedding.embed_documents([words(21)])[0]) == 4
    assert emb.token_counts([words(22)]) == [46]
    with pytest.raises(lm.ModelError, match='pair limit'):
        embedding.embed_documents([words(22)])
    assert len(reranking.score(words(8), [words(21)])) == 1
    with pytest.raises(lm.ModelError, match='8-token limit'):
        embedding.embed_query(words(9))
    data, raws = make_corpus({'a': [words(40)]})
    snapshot = build.build_index(root.parent / 'comparator-index', data, embedder=embedding,
                                 reranker_identity=reranking.identity)
    assert snapshot['manifest']['dimensions'] == 4 and snapshot['manifest']['embedding'] == embedding.identity
    for unit in snapshot['corpus']['units']:
        assert embedding.passage_tokens([unit['indexed_text']])[0] <= embedding.token_window
    assert ''.join(u['evidence']['text'] for u in snapshot['corpus']['units']) == words(40)
    assert counted == []


def test_external_weights_load_from_a_verified_materialized_directory(tmp_path, counted):
    root = tmp_path / 'models'
    doc = add_comparator(root, make_installation(root), external=True, tmp=tmp_path)
    entry = doc['models']['fictional-comparator']
    assert entry['onnx']['external_data'] == ['model_data']
    emb = lm.Embedder('fictional-comparator', root=root, doc=doc, tokenizer_factory=comparator_factory)
    assert lm.qualify(emb)['passed'] and emb.embed_passages(['zorvel quenth']).vectors.shape == (1, 4)
    folder = root / 'materialized' / f"fictional-comparator-{entry['revision']}" / 'onnx'
    assert sorted(p.name for p in folder.iterdir()) == ['model.onnx', 'model.onnx_data']
    data = lm._stored(root, entry['files']['model_data'])
    data.write_bytes(data.read_bytes()[:-4] + b'\x00\x00\x80\x7f')
    (folder / 'model.onnx_data').unlink()
    with pytest.raises(lm.ModelError, match='differs from its pin'):
        lm.Embedder('fictional-comparator', root=root, doc=doc, tokenizer_factory=comparator_factory)
    data.unlink()
    with pytest.raises(lm.ModelError, match='prefetch'):
        lm.Embedder('fictional-comparator', root=root, doc=doc, tokenizer_factory=comparator_factory)
    bad = copy.deepcopy(doc)
    bad['models']['fictional-comparator']['onnx']['external_data'] = ['tokenizer']
    with pytest.raises(lm.ModelError, match='external data'):
        lm.validate_catalogue(bad)
    assert counted == []
