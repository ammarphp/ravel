"""Pinned local literature models: dense passage embeddings and cross-encoder reranking.

The models are trusted installation assets declared in ``knowledge/models.json``:
an upstream repository, an immutable revision, and the size and sha256 of every
file and licence notice. Only the explicit ``prefetch`` operation uses the
network. Loading reads the verified bytes and refuses a missing or altered file;
it never downloads, contacts a model hub, executes upstream code or falls back to
another model. Inference uses the existing ONNX Runtime CPU provider with pinned
thread counts, length-sorted batches and per-batch padding under the attention
mask. An identical call with identical settings returns identical bits on one
platform. ``qualify`` measures the installed pipeline against the pinned
reference token ids and outputs, and the size of batch effects, on this platform.

Embedding inputs longer than the model window are refused, never truncated:
callers split located units before embedding them. A reranker passage that does
not fit beside its query is truncated only with an explicit per-item flag. This
module performs no generative model call and no scientific inference.
"""
from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import statistics
import struct
import time

from ravel.workflow.literature_provider import canonical

SCHEMA_VERSION = 1
ROLES = ('embedding', 'reranker')
ROOT_ENV = 'RAVEL_LITERATURE_MODELS'
PROVIDER = 'CPUExecutionProvider'
MAX_ITEMS = 4096
MAX_TEXT_BYTES = 64 * 1024
MAX_THREADS = 64
MAX_BATCH = 128
LICENCES = ('MIT', 'Apache-2.0', 'BSD-2-Clause', 'BSD-3-Clause')
_INPUTS = ('input_ids', 'attention_mask', 'token_type_ids')
_HEX64 = re.compile(r'[0-9a-f]{64}')
_ID = re.compile(r'[a-z0-9][a-z0-9.\-]{0,63}')
_REPOSITORY = re.compile(r'[A-Za-z0-9][A-Za-z0-9._\-]{0,95}/[A-Za-z0-9][A-Za-z0-9._\-]{0,95}')


class ModelError(ValueError):
    """A pinned model is unavailable, altered, or used outside its declared contract."""


# ---------------------------------------------------------------- catalogue

def _require(condition, message):
    if not condition:
        raise ModelError('invalid model catalogue: ' + message)


def _bounded_int(value, low, high):
    return type(value) is int and low <= value <= high


def _check_pin(pin, where):
    _require(isinstance(pin, dict) and _bounded_int(pin.get('size'), 1, 1 << 34)
             and isinstance(pin.get('sha256'), str) and _HEX64.fullmatch(pin['sha256']),
             where + ' needs a positive size and a sha256')


def _check_relative(path, where):
    pure = PurePosixPath(path) if isinstance(path, str) else None
    _require(pure is not None and path and not pure.is_absolute() and '..' not in pure.parts
             and '\\' not in path, where + ' path must stay inside the pinned revision')


def _check_probes(model):
    q = model['qualification']
    role = model['role']
    _require(isinstance(q, dict) and isinstance(q.get('reference'), dict)
             and isinstance(q.get('tolerance'), dict), model['id'] + ' qualification')
    tol = q['tolerance']
    probes = q.get('probes')
    _require(isinstance(probes, list) and 1 <= len(probes) <= 32, model['id'] + ' needs 1-32 probes')
    for probe in probes:
        _require(isinstance(probe, dict) and isinstance(probe.get('token_ids'), list)
                 and all(_bounded_int(t, 0, 1 << 24) for t in probe['token_ids']),
                 model['id'] + ' probe token ids')
        if role == 'embedding':
            _require(probe.get('kind') in ('query', 'passage') and isinstance(probe.get('text'), str)
                     and isinstance(probe.get('vector_f32le_b64'), str), model['id'] + ' embedding probe')
            raw = base64.b64decode(probe['vector_f32le_b64'], validate=True)
            _require(len(raw) == 4 * model['embedding']['dimension']
                     and all(math.isfinite(x) for x in struct.unpack(f'<{len(raw) // 4}f', raw)),
                     model['id'] + ' probe vector width and finiteness')
        else:
            _require(isinstance(probe.get('query'), str) and isinstance(probe.get('passage'), str)
                     and isinstance(probe.get('score'), (int, float)) and type(probe['score']) is not bool
                     and math.isfinite(probe['score']), model['id'] + ' reranker probe')
    keys = {'max_abs', 'min_cosine'} if role == 'embedding' else {'max_abs'}
    _require(set(tol) == keys and all(isinstance(tol[k], float) and 0 < tol[k] <= 1 for k in keys),
             model['id'] + ' tolerance')


def _check_model(model_id, model):
    _require(_ID.fullmatch(model_id) is not None, 'model id ' + repr(model_id))
    _require(model.get('id') == model_id and model.get('role') in ROLES, model_id + ' role')
    _require(model.get('host') == 'https://huggingface.co'
             and isinstance(model.get('repository'), str) and _REPOSITORY.fullmatch(model['repository'])
             and isinstance(model.get('revision'), str) and re.fullmatch(r'[0-9a-f]{40}', model['revision']),
             model_id + ' needs an https host, repository and full revision')
    lic = model.get('license')
    _require(isinstance(lic, dict) and lic.get('spdx') in LICENCES, model_id + ' licence is not admitted')
    declared = lic.get('declared_by')
    _require(isinstance(declared, dict) and isinstance(declared.get('file'), str)
             and isinstance(declared.get('value'), str), model_id + ' licence declaration')
    notice = lic.get('notice')
    _check_pin(notice, model_id + ' licence notice')
    _require(isinstance(notice.get('url'), str) and notice['url'].startswith('https://'),
             model_id + ' licence notice url')
    names = model.get('files')
    _require(isinstance(names, dict) and {'model', 'tokenizer'} <= set(names), model_id + ' files')
    for name, pin in names.items():
        _check_pin(pin, f'{model_id} file {name}')
        _check_relative(pin.get('path'), f'{model_id} file {name}')
    _require(declared['file'] in {pin['path'] for pin in names.values()},
             model_id + ' licence declaration must be a pinned file')
    _require(declared['value'] == 'license: ' + lic['spdx'].lower(),
             model_id + ' licence declaration must name the admitted licence')
    onnx = model.get('onnx')
    _require(isinstance(onnx, dict) and isinstance(onnx.get('inputs'), list)
             and {'input_ids', 'attention_mask'} <= set(onnx['inputs']) <= set(_INPUTS)
             and len(set(onnx['inputs'])) == len(onnx['inputs']) and isinstance(onnx.get('output'), str)
             and set(onnx) <= {'inputs', 'output', 'external_data'},
             model_id + ' onnx signature')
    external = onnx.get('external_data', [])
    _require(isinstance(external, list) and len(set(external)) == len(external)
             and all(isinstance(n, str) and n in names and n not in ('model', 'tokenizer') for n in external)
             and all(PurePosixPath(names[n]['path']).parent == PurePosixPath(names['model']['path']).parent
                     for n in external),
             model_id + ' onnx external data must be pinned files beside the model')
    tok = model.get('tokenizer')
    _require(isinstance(tok, dict) and _bounded_int(tok.get('max_tokens'), 8, 8192)
             and isinstance(tok.get('pad_token'), str) and _bounded_int(tok.get('pad_id'), 0, 1 << 24),
             model_id + ' tokenizer contract')
    if model['role'] == 'embedding':
        emb = model.get('embedding')
        _require(isinstance(emb, dict) and emb.get('pooling') == 'cls' and emb.get('normalize') == 'l2'
                 and _bounded_int(emb.get('dimension'), 1, 8192)
                 and isinstance(emb.get('query_prefix'), str) and isinstance(emb.get('passage_prefix'), str),
                 model_id + ' embedding contract (CLS pooling, L2 normalisation)')
    else:
        rr = model.get('reranker')
        _require(isinstance(rr, dict) and rr.get('score') == 'logit'
                 and rr.get('truncation') == 'only_second'
                 and _bounded_int(rr.get('max_query_tokens'), 1, tok['max_tokens'] // 2),
                 model_id + ' reranker contract')
    _check_probes(model)


def validate_catalogue(doc) -> dict:
    """Return a checked copy of a model catalogue; raise ModelError on any defect."""
    _require(isinstance(doc, dict) and doc.get('schema_version') == SCHEMA_VERSION, 'schema_version')
    runtime = doc.get('runtime')
    _require(isinstance(runtime, dict) and runtime.get('provider') == PROVIDER
             and _bounded_int(runtime.get('threads'), 1, MAX_THREADS)
             and _bounded_int(runtime.get('batch_size'), 1, MAX_BATCH)
             and runtime.get('pad_multiple') in (1, 2, 4, 8, 16, 32, 64), 'runtime')
    models = doc.get('models')
    _require(isinstance(models, dict) and models, 'models')
    for model_id, model in models.items():
        _check_model(model_id, model)
        _require(model['tokenizer']['max_tokens'] % runtime['pad_multiple'] == 0,
                 model_id + ' window must be a multiple of the padding multiple')
    defaults = doc.get('defaults')
    _require(isinstance(defaults, dict) and set(defaults) == set(ROLES)
             and all(defaults[r] in models and models[defaults[r]]['role'] == r for r in ROLES),
             'every role needs a default model of that role')
    return deepcopy(doc)


def _refuse_constant(name):
    raise ModelError('invalid model catalogue: non-finite constant ' + name)


@lru_cache(maxsize=1)
def _packaged():
    return validate_catalogue(json.loads(
        files('ravel.data').joinpath('knowledge/models.json').read_text(encoding='utf-8'),
        parse_constant=_refuse_constant))


def catalogue() -> dict:
    """The packaged, validated model catalogue."""
    return deepcopy(_packaged())


def _doc(doc):
    return _packaged() if doc is None else validate_catalogue(doc)


def model_entry(model_id=None, *, role=None, doc=None) -> dict:
    """One catalogue entry, by id or as the declared default for ``role``."""
    doc = _doc(doc)
    if model_id is None:
        if role not in ROLES:
            raise ModelError('a model id or a role is required')
        model_id = doc['defaults'][role]
    model = doc['models'].get(model_id)
    if model is None or (role is not None and model['role'] != role):
        raise ModelError(f'no pinned {role or "literature"} model {model_id!r}')
    return deepcopy(model)


def default_root() -> Path:
    """``$RAVEL_LITERATURE_MODELS``, else ``literature-models`` in the per-user shared data directory."""
    override = os.environ.get(ROOT_ENV)
    if override:
        return Path(override).expanduser()
    from ravel.paths import shared_native_build
    return shared_native_build() / 'literature-models'


# ---------------------------------------------------------------- custody

def _file_url(model, pin):
    return f"{model['host']}/{model['repository']}/resolve/{model['revision']}/{pin['path']}"


def _pins(model):
    """(name, url, pin) for every model file and the licence notice."""
    rows = [(name, _file_url(model, pin), pin) for name, pin in sorted(model['files'].items())]
    return rows + [('licence_notice', model['license']['notice']['url'], model['license']['notice'])]


def _stored(root, pin):
    # Same content-addressed layout as the installer's download cache.
    return Path(root) / 'sha256' / pin['sha256']


def _declaring_file(model):
    path = model['license']['declared_by']['file']
    return next(name for name, pin in sorted(model['files'].items()) if pin['path'] == path)


def _licence_declared(data, model):
    """Whether the pinned model card's front matter carries the catalogued licence line."""
    lines = data.decode('utf-8', errors='replace').splitlines()
    if not lines or lines[0].rstrip() != '---':
        return False
    end = next((i for i, line in enumerate(lines[1:], 1) if line.rstrip() == '---'), None)
    value = model['license']['declared_by']['value']
    return end is not None and value in (line.rstrip() for line in lines[1:end])


def _require_declared_licence(data, model):
    if not _licence_declared(data, model):
        raise ModelError(f"{model['id']} model card does not declare "
                         f"{model['license']['declared_by']['value']}; its licence is unverified, "
                         'so the model is not used')


def prefetch(model_ids=None, *, root=None, opener=None, timeout=60, doc=None) -> dict:
    """Explicitly download and verify the pinned files; the only networked operation.

    Without ``model_ids`` the default model of every role is fetched. Verified
    files already present cause no request. A digest mismatch quarantines the
    download and raises; nothing partial is ever reported as installed. A model
    card that does not declare the catalogued licence is refused.
    """
    from ravel.setup.fetch import FetchError, Fetcher
    doc = _doc(doc)
    if model_ids is not None and (not isinstance(model_ids, (list, tuple))
                                  or not all(isinstance(i, str) for i in model_ids)):
        raise ModelError('model_ids must be a list of model ids')
    ids = sorted(set(doc['defaults'].values())) if model_ids is None else list(dict.fromkeys(model_ids))
    models = [model_entry(i, doc=doc) for i in ids]
    root = Path(root) if root is not None else default_root()
    fetcher = Fetcher(root, opener=opener, timeout=timeout)
    report = []
    for model in models:
        rows = []
        for name, url, pin in _pins(model):
            try:
                path = fetcher.fetch(url, {'sha256': pin['sha256'], 'size': pin['size']})
            except FetchError as exc:
                raise ModelError(f"prefetch of {model['id']} {name} failed: {exc}") from exc
            rows.append({'name': name, 'sha256': pin['sha256'], 'size': pin['size'], 'path': str(path)})
        _require_declared_licence(_stored(root, model['files'][_declaring_file(model)]).read_bytes(), model)
        report.append({'model_id': model['id'], 'revision': model['revision'], 'files': rows})
    return {'root': str(root), 'models': report, 'network_requests': list(fetcher.network_requests)}


def _digest(path):
    sha, size = hashlib.sha256(), 0
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            sha.update(chunk)
            size += len(chunk)
    return sha.hexdigest(), size


def verify(model_id=None, *, role=None, root=None, doc=None) -> dict:
    """Report whether every pinned file is present and intact; reads only, never repairs."""
    model = model_entry(model_id, role=role, doc=doc)
    root = Path(root) if root is not None else default_root()
    rows = []
    for name, _url, pin in _pins(model):
        path = _stored(root, pin)
        if not path.is_file():
            status = 'missing'
        else:
            sha, size = _digest(path)
            status = 'ok' if (sha, size) == (pin['sha256'], pin['size']) else 'altered'
        rows.append({'name': name, 'status': status, 'path': str(path)})
    card = _declaring_file(model)
    declared = (_licence_declared(_stored(root, model['files'][card]).read_bytes(), model)
                if next(r['status'] for r in rows if r['name'] == card) == 'ok' else None)
    return {'model_id': model['id'], 'role': model['role'], 'root': str(root),
            'complete': all(r['status'] == 'ok' for r in rows) and declared is True,
            'licence_declared': declared, 'files': rows}


def inspect(*, root=None, doc=None) -> dict:
    """Installation status of every pinned model, for doctor/inspect surfaces."""
    doc = _doc(doc)
    return {'defaults': dict(doc['defaults']),
            'models': [verify(m, root=root, doc=doc) for m in sorted(doc['models'])]}


def _read_verified(root, model, name):
    pin = model['files'][name]
    path = _stored(root, pin)
    try:
        data = path.read_bytes()
    except OSError:
        raise ModelError(f"{model['id']} {name} is not installed under {root}; "
                         'run the explicit literature model prefetch') from None
    if len(data) != pin['size'] or hashlib.sha256(data).hexdigest() != pin['sha256']:
        raise ModelError(f"{model['id']} {name} differs from its pin; it was not loaded")
    return data


def _model_source(root, model):
    """The verified ONNX model: its bytes, or a verified directory when it carries external data.

    External tensor files are resolved by name beside the model, so the verified
    content-addressed files are hard-linked (or copied) under their pinned names into
    ``<root>/materialized/<model id>-<revision>``, and every file is re-hashed there
    before ONNX Runtime opens it. Nothing is fetched.
    """
    external = model['onnx'].get('external_data', [])
    if not external:
        return _read_verified(root, model, 'model')
    import shutil
    folder = Path(root) / 'materialized' / f"{model['id']}-{model['revision']}"
    for name in ['model', *external]:
        pin = model['files'][name]
        source = _stored(root, pin)
        if not source.is_file():
            raise ModelError(f"{model['id']} {name} is not installed under {root}; "
                             'run the explicit literature model prefetch')
        target = folder / pin['path']
        if not target.is_file() or _digest(target) != (pin['sha256'], pin['size']):
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            try:
                os.link(source, target)
            except OSError:
                shutil.copyfile(source, target)
        if target.is_symlink() or _digest(target) != (pin['sha256'], pin['size']):
            raise ModelError(f"{model['id']} {name} differs from its pin; it was not loaded")
    return str(folder / model['files']['model']['path'])


# ---------------------------------------------------------------- inference

def _runtime(doc, threads, batch_size):
    runtime = doc['runtime']
    threads = runtime['threads'] if threads is None else threads
    batch_size = runtime['batch_size'] if batch_size is None else batch_size
    if not _bounded_int(threads, 1, MAX_THREADS) or not _bounded_int(batch_size, 1, MAX_BATCH):
        raise ModelError(f'threads must be 1-{MAX_THREADS} and batch_size 1-{MAX_BATCH}')
    return threads, batch_size


def _missing():
    return ModelError('literature models require the full Python installation, '
                      'including numpy, onnxruntime and tokenizers')


def _tokenizers(text, model):
    """Two independent tokenizers from the verified definition: plain and passage-truncating."""
    try:
        import tokenizers
    except ImportError as exc:
        raise _missing() from exc
    plain, truncating = tokenizers.Tokenizer.from_str(text), tokenizers.Tokenizer.from_str(text)
    # Padding and truncation are applied here, never by the tokenizer file's defaults.
    for tok in (plain, truncating):
        tok.no_padding()
        tok.no_truncation()
    if model['role'] == 'reranker':
        truncating.enable_truncation(model['tokenizer']['max_tokens'], strategy='only_second')
    return plain, truncating, tokenizers.__version__


def _session(ort, data, model, threads):
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    options.log_severity_level = 3
    # Idle worker threads must not busy-wait on a shared machine.
    options.add_session_config_entry('session.intra_op.allow_spinning', '0')
    session = ort.InferenceSession(data, sess_options=options, providers=[PROVIDER])
    declared = model['onnx']
    inputs = {i.name: i for i in session.get_inputs()}
    if set(inputs) != set(declared['inputs']) or any(
            i.type != 'tensor(int64)' or len(i.shape) != 2 for i in inputs.values()):
        raise ModelError(f"{model['id']} ONNX inputs differ from the declared signature")
    outputs = {o.name: o for o in session.get_outputs()}
    out = outputs.get(declared['output'])
    want = (3, model['embedding']['dimension']) if model['role'] == 'embedding' else (2, 1)
    if out is None or out.type != 'tensor(float)' or len(out.shape) != want[0] or out.shape[-1] != want[1]:
        raise ModelError(f"{model['id']} ONNX output differs from the declared signature")
    return session


class _Loaded:
    """Shared custody, tokenizer and batching for one pinned model."""

    def __init__(self, model, *, root, threads, batch_size, doc, tokenizer_factory=None):
        try:
            import numpy as np
            import onnxruntime as ort
        except ImportError as exc:
            raise _missing() from exc
        self.model, self.np = model, np
        doc = _doc(doc)
        self.threads, self.batch_size = _runtime(doc, threads, batch_size)
        self.pad_multiple = doc['runtime']['pad_multiple']
        self.max_tokens = model['tokenizer']['max_tokens']
        self.pad_id = model['tokenizer']['pad_id']
        root = Path(root) if root is not None else default_root()
        _require_declared_licence(_read_verified(root, model, _declaring_file(model)), model)
        text = _read_verified(root, model, 'tokenizer').decode('utf-8')
        # The factory seam lets tests substitute the tokenizer library; custody stays in force.
        self.tokenizer, self.truncating, tok_version = (tokenizer_factory or _tokenizers)(text, model)
        if self.tokenizer.token_to_id(model['tokenizer']['pad_token']) != self.pad_id:
            raise ModelError(f"{model['id']} tokenizer padding token differs from its contract")
        self.session = _session(ort, _model_source(root, model), model, self.threads)
        self.versions = {'onnxruntime': ort.__version__, 'tokenizers': tok_version}
        m = model
        self._semantic = {'model_id': m['id'], 'role': m['role'], 'repository': m['repository'],
                          'revision': m['revision'],
                          'files': {k: v['sha256'] for k, v in sorted(m['files'].items())},
                          'onnx': m['onnx'], 'tokenizer': m['tokenizer'], m['role']: m[m['role']]}
        self.identity_sha256 = hashlib.sha256(canonical(self._semantic)).hexdigest()

    def identity(self) -> dict:
        """Model identity (what determines outputs) and runtime identity (numerics within tolerance)."""
        return {**deepcopy(self._semantic), 'identity_sha256': self.identity_sha256,
                'runtime': {**self.versions, 'provider': PROVIDER, 'threads': self.threads,
                            'inter_op_threads': 1, 'batch_size': self.batch_size,
                            'pad_multiple': self.pad_multiple,
                            'graph_optimization': 'all', 'system': platform.system(),
                            'machine': platform.machine()}}

    def _run(self, encodings):
        """Run length-sorted batches; return each encoding's first output position, in input order.

        That position is the CLS state of an embedding or the single reranker
        logit. It is copied, so no batch's full output outlives the batch.
        The batch plan depends only on the input list, so identical calls are
        repeatable. Every batch is padded to a multiple of ``pad_multiple`` tokens:
        masked positions add exact zeros without moving a real token into another
        vector lane or scalar tail. The pinned models then gave outputs bitwise
        independent of batch companions and thread count on the measured ARM and
        x86 AVX-512 CPUs. That is a kernel property, not a guarantee (a generic
        sequence reduction differs in the last bits on x86), so ``qualify`` reports it.
        """
        np = self.np
        names = self.model['onnx']['inputs']
        order = sorted(range(len(encodings)), key=lambda i: (len(encodings[i][0]), i))
        rows = [None] * len(encodings)
        m = self.pad_multiple
        for start in range(0, len(order), self.batch_size):
            chunk = order[start:start + self.batch_size]
            width = -(-max(len(encodings[i][0]) for i in chunk) // m) * m
            ids = np.full((len(chunk), width), self.pad_id, dtype=np.int64)
            mask = np.zeros((len(chunk), width), dtype=np.int64)
            types = np.zeros((len(chunk), width), dtype=np.int64)
            for r, i in enumerate(chunk):
                tokens, type_ids = encodings[i]
                ids[r, :len(tokens)] = tokens
                mask[r, :len(tokens)] = 1
                types[r, :len(tokens)] = type_ids
            feed = {'input_ids': ids, 'attention_mask': mask, 'token_type_ids': types}
            out = np.asarray(self.session.run([self.model['onnx']['output']], {n: feed[n] for n in names})[0])
            if out.shape[0] != len(chunk) or not np.isfinite(out).all():
                raise ModelError(f"{self.model['id']} produced a non-finite or incomplete output")
            for r, i in enumerate(chunk):
                rows[i] = out[r, 0].copy()
        return rows


def _texts(values, what):
    if not isinstance(values, (list, tuple)) or not 1 <= len(values) <= MAX_ITEMS:
        raise ModelError(f'a list of 1-{MAX_ITEMS} {what} is required')
    for value in values:
        if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > MAX_TEXT_BYTES:
            raise ModelError(f'{what} must be non-blank text of at most {MAX_TEXT_BYTES} bytes each')
    return list(values)


@dataclass(frozen=True)
class Embeddings:
    vectors: object                 # numpy float32 [n, dimension], unit L2 rows, read-only
    token_counts: tuple
    identity_sha256: str


@dataclass(frozen=True)
class Scores:
    scores: tuple                   # raw cross-encoder logits, in input order
    token_counts: tuple
    truncated: tuple
    identity_sha256: str


class Embedder(_Loaded):
    """CLS-pooled, L2-normalised dense vectors from the pinned embedding model."""

    def __init__(self, model_id=None, *, root=None, threads=None, batch_size=None, doc=None,
                 tokenizer_factory=None):
        super().__init__(model_entry(model_id, role='embedding', doc=doc), root=root, threads=threads,
                         batch_size=batch_size, doc=doc, tokenizer_factory=tokenizer_factory)

    def _encode(self, texts, kind):
        spec = self.model['embedding']
        prefix = spec['query_prefix'] if kind == 'query' else spec['passage_prefix']
        out = []
        for text in texts:
            enc = self.tokenizer.encode(prefix + text)
            out.append((list(enc.ids), list(enc.type_ids)))
        return out

    def token_counts(self, texts, *, kind='passage') -> list:
        """Model-window tokens per text, including the instruction prefix and special tokens."""
        if kind not in ('query', 'passage'):
            raise ModelError('kind must be query or passage')
        return [len(ids) for ids, _ in self._encode(_texts(texts, 'texts'), kind)]

    def _embed(self, texts, kind):
        encodings = self._encode(_texts(texts, 'texts'), kind)
        over = [i for i, (ids, _) in enumerate(encodings) if len(ids) > self.max_tokens]
        if over:
            raise ModelError(f'{len(over)} input(s) exceed the {self.max_tokens}-token window '
                             f'(first indices {over[:8]}); split them before embedding')
        np = self.np
        cls = np.stack(self._run(encodings)).astype(np.float32)
        norms = np.linalg.norm(cls.astype(np.float64), axis=1)
        if not np.all(norms > 0):
            raise ModelError(f"{self.model['id']} produced a zero vector")
        vectors = (cls / norms[:, None]).astype(np.float32)
        vectors.setflags(write=False)
        return Embeddings(vectors, tuple(len(ids) for ids, _ in encodings), self.identity_sha256)

    def embed_passages(self, texts) -> Embeddings:
        return self._embed(texts, 'passage')

    def embed_queries(self, texts) -> Embeddings:
        return self._embed(texts, 'query')


class Reranker(_Loaded):
    """Cross-encoder relevance logits for (query, passage) pairs from the pinned reranker."""

    def __init__(self, model_id=None, *, root=None, threads=None, batch_size=None, doc=None,
                 tokenizer_factory=None):
        super().__init__(model_entry(model_id, role='reranker', doc=doc), root=root, threads=threads,
                         batch_size=batch_size, doc=doc, tokenizer_factory=tokenizer_factory)

    def _encode(self, query, passages):
        limit = self.model['reranker']['max_query_tokens']
        if len(self.tokenizer.encode(query, add_special_tokens=False).ids) > limit:
            raise ModelError(f'query exceeds {limit} tokens')
        out, truncated = [], []
        for passage in passages:
            enc = self.tokenizer.encode(query, passage)
            cut = len(enc.ids) > self.max_tokens
            if cut:
                enc = self.truncating.encode(query, passage)
                if len(enc.ids) > self.max_tokens:
                    raise ModelError(f"{self.model['id']} could not fit a passage beside the query")
            out.append((list(enc.ids), list(enc.type_ids)))
            truncated.append(cut)
        return out, truncated

    def score(self, query, passages) -> Scores:
        query = _texts([query], 'queries')[0]
        encodings, truncated = self._encode(query, _texts(passages, 'passages'))
        rows = self._run(encodings)
        return Scores(tuple(float(r) for r in rows), tuple(len(ids) for ids, _ in encodings),
                      tuple(truncated), self.identity_sha256)

    def rank(self, query, candidates) -> list:
        """Order ``(key, passage)`` pairs by descending logit; ties keep ascending key order."""
        keys = [k for k, _ in candidates]
        if len(set(keys)) != len(keys) or not all(isinstance(k, str) for k in keys):
            raise ModelError('candidate keys must be distinct strings')
        scored = self.score(query, [p for _, p in candidates])
        rows = [{'key': k, 'score': s, 'truncated': t, 'token_count': n}
                for k, s, t, n in zip(keys, scored.scores, scored.truncated, scored.token_counts)]
        return sorted(rows, key=lambda r: (-r['score'], r['key']))


# ---------------------------------------------------------------- qualification

def _vector(probe):
    import numpy as np
    return np.frombuffer(base64.b64decode(probe['vector_f32le_b64']), dtype='<f4').astype(np.float32)


def qualify(loaded) -> dict:
    """Compare the installed pipeline with the pinned reference probes on this platform.

    Required: token ids equal to the reference, outputs within the declared
    tolerance of the reference, batch companions moving an output by no more
    than that tolerance, and a repeated identical call returning identical bits.
    Bitwise batch invariance is reported, not required: it holds on some CPU
    kernels and not on others. The report keeps the measured deviations; it
    never adjusts a reference.
    """
    np = loaded.np
    model = loaded.model
    q = model['qualification']
    probes = q['probes']
    tol = q['tolerance']
    if model['role'] == 'embedding':
        encodings = [loaded._encode([p['text']], p['kind'])[0] for p in probes]
        alone = np.stack([loaded._embed([p['text']], p['kind']).vectors[0] for p in probes])

        def together():
            out = np.empty_like(alone)
            for kind in ('query', 'passage'):
                idx = [i for i, p in enumerate(probes) if p['kind'] == kind]
                if idx:
                    out[idx] = loaded._embed([probes[i]['text'] for i in idx], kind).vectors
            return out
        ref = np.stack([_vector(p) for p in probes]).astype(np.float64)
        got = alone.astype(np.float64)
        cosines = np.sum(got * ref, axis=1) / np.linalg.norm(ref, axis=1)
        measured = {'max_abs': float(np.abs(got - ref).max()), 'min_cosine': float(cosines.min())}
        within = measured['max_abs'] <= tol['max_abs'] and measured['min_cosine'] >= tol['min_cosine']
    else:
        encodings = [loaded._encode(p['query'], [p['passage']])[0][0] for p in probes]
        alone = np.asarray([loaded.score(p['query'], [p['passage']]).scores[0] for p in probes])

        def together():
            out = np.empty_like(alone)
            for query in dict.fromkeys(p['query'] for p in probes):
                idx = [i for i, p in enumerate(probes) if p['query'] == query]
                out[idx] = loaded.score(query, [probes[i]['passage'] for i in idx]).scores
            return out
        ref = np.asarray([p['score'] for p in probes], dtype=np.float64)
        measured = {'max_abs': float(np.max(np.abs(alone - ref)))}
        within = measured['max_abs'] <= tol['max_abs']
    first, second = together(), together()
    measured['batch_max_abs'] = float(np.max(np.abs(first.astype(np.float64) - alone.astype(np.float64))))
    batch_within = measured['batch_max_abs'] <= tol['max_abs']
    repeatable = bool(np.array_equal(first, second))
    tokens_equal = [list(ids) == p['token_ids'] for (ids, _), p in zip(encodings, probes)]
    return {'model_id': model['id'], 'identity': loaded.identity(), 'probes': len(probes),
            'token_ids_equal': all(tokens_equal),
            'token_mismatches': [i for i, ok in enumerate(tokens_equal) if not ok],
            'measured': measured, 'tolerance': dict(tol), 'within_tolerance': within,
            'batch_within_tolerance': batch_within, 'repeatable': repeatable,
            'batch_invariant': bool(np.array_equal(first, alone)), 'reference': deepcopy(q['reference']),
            'passed': all(tokens_equal) and within and batch_within and repeatable}


def measure_rerank_latency(reranker, query, passages, *, repeats=5) -> dict:
    """Wall-clock seconds to score one query against ``passages`` (one warm-up call excluded)."""
    if not _bounded_int(repeats, 1, 100):
        raise ModelError('repeats must be 1-100')
    first = reranker.score(query, passages)
    seconds = []
    for _ in range(repeats):
        start = time.perf_counter()
        reranker.score(query, passages)
        seconds.append(time.perf_counter() - start)
    counts = sorted(first.token_counts)
    load = os.getloadavg()[0] if hasattr(os, 'getloadavg') else None
    return {'model_id': reranker.model['id'], 'passages': len(passages),
            'pair_tokens': {'median': statistics.median(counts), 'max': counts[-1]},
            'truncated': sum(first.truncated), 'seconds': [round(s, 4) for s in seconds],
            'median_seconds': round(statistics.median(seconds), 4), 'max_seconds': round(max(seconds), 4),
            'runtime': reranker.identity()['runtime'], 'cpu_count': os.cpu_count(), 'load_average_1m': load}


# ---------------------------------------------------------------- index adapters

def pair_limits(embedding_model, reranker_model) -> dict:
    """Passage and query token limits under which a reranker pair is never truncated.

    A pair is ``[CLS] query [SEP] passage [SEP]``: a passage whose standalone reranker
    encoding (its own two special tokens included) has at most
    ``max_tokens - max_query_tokens - 1`` tokens fits beside any query of at most
    ``max_query_tokens`` content tokens. With a shared tokenizer that bound and the
    embedding model's own window give one passage limit (383 beside 128 for the pinned
    defaults). With different tokenizers each model counts in its own tokens:
    ``passage_tokens`` is the embedding window and ``reranker_passage_tokens`` the pair bound.
    """
    if embedding_model['role'] != 'embedding' or reranker_model['role'] != 'reranker':
        raise ModelError('pair limits need one embedding and one reranker model')
    if embedding_model['embedding']['passage_prefix']:
        raise ModelError('the pair limit requires passages without an instruction prefix')
    query = reranker_model['reranker']['max_query_tokens']
    bound = reranker_model['tokenizer']['max_tokens'] - query - 1
    window = embedding_model['tokenizer']['max_tokens']
    if bound < 3 or window < 3:
        raise ModelError('the reranker window leaves no room for a passage beside its query')
    if embedding_model['files']['tokenizer']['sha256'] == reranker_model['files']['tokenizer']['sha256']:
        return {'passage_tokens': min(window, bound), 'query_tokens': query}
    return {'passage_tokens': window, 'query_tokens': query, 'reranker_passage_tokens': bound}


def _qualified(loaded, report):
    if not isinstance(report, dict) or report.get('passed') is not True:
        raise ModelError(f"{loaded.model['id']} is not qualified on this platform; run the explicit qualification")
    identity = loaded.identity()
    if (report.get('model_id') != loaded.model['id'] or not isinstance(report.get('identity'), dict)
            or report['identity'].get('identity_sha256') != identity['identity_sha256']
            or report['identity'].get('runtime') != identity['runtime']):
        raise ModelError(f"{loaded.model['id']} qualification belongs to another model or runtime")
    return hashlib.sha256(canonical(report)).hexdigest()


def _index_identity(loaded, qualification_sha256, limits, kind):
    identity = loaded.identity()
    return {'kind': kind, 'model_id': identity['model_id'], 'identity_sha256': identity['identity_sha256'],
            'tokenizer_sha256': loaded.model['files']['tokenizer']['sha256'], 'runtime': identity['runtime'],
            'qualification_sha256': qualification_sha256, 'pair_limits': dict(limits)}


class IndexEmbedder:
    """The index embedding adapter: qualified pinned model, explicit token windows, no truncation.

    ``identity`` (recorded in the index manifest) binds the model semantics, the
    tokenizer file, the runtime and the qualification report, so a changed asset,
    runtime or qualification makes an existing index stale. Passages above the
    pair limit and queries above the query limit are refused; the index build
    splits units with ``passage_tokens`` before embedding.
    """

    def __init__(self, embedder, reranker, *, qualification):
        # ``reranker`` is the loaded reranker, or its catalogue entry when both share one tokenizer.
        self._embedder = embedder
        model = reranker.model if isinstance(reranker, _Loaded) else reranker
        limits = pair_limits(embedder.model, model)
        self._reranker_bound = limits.get('reranker_passage_tokens')
        if self._reranker_bound is not None and not isinstance(reranker, _Loaded):
            raise ModelError('different embedding and reranker tokenizers need the loaded reranker to count pairs')
        self._reranker = reranker if isinstance(reranker, _Loaded) else None
        self.token_window, self.query_window = limits['passage_tokens'], limits['query_tokens']
        self.identity = _index_identity(embedder, _qualified(embedder, qualification), limits,
                                        'literature-index-embedding')

    def passage_tokens(self, texts) -> list:
        """Window counts compared with ``token_window``: the embedding count, or with two tokenizers
        the larger excess over either model's own bound (so a count fits only when both fit)."""
        texts = list(texts)
        counts = self._embedder.token_counts(texts, kind='passage')
        if self._reranker_bound is None:
            return counts
        pairs = [len(self._reranker.tokenizer.encode(text).ids) for text in texts]
        return [max(e, r + self.token_window - self._reranker_bound) for e, r in zip(counts, pairs)]

    def query_tokens(self, text) -> int:
        tokenizer = (self._reranker or self._embedder).tokenizer
        return len(tokenizer.encode(text, add_special_tokens=False).ids)

    def embed_documents(self, texts):
        texts = list(texts)
        over = [i for i, n in enumerate(self.passage_tokens(texts)) if n > self.token_window]
        if over:
            raise ModelError(f'{len(over)} passage(s) exceed the {self.token_window}-token pair limit '
                             f'(first indices {over[:8]}); split them before embedding')
        return [[float(x) for x in row] for row in self._embedder.embed_passages(texts).vectors]

    def embed_query(self, text):
        if self.query_tokens(text) > self.query_window:
            raise ModelError(f'query exceeds the {self.query_window}-token limit')
        return [float(x) for x in self._embedder.embed_queries([text]).vectors[0]]


class IndexReranker:
    """The index reranking adapter: a passage that would be truncated beside its query is refused."""

    def __init__(self, reranker, embedding_model, *, qualification):
        self._reranker = reranker
        limits = pair_limits(embedding_model, reranker.model)
        self.identity = _index_identity(reranker, _qualified(reranker, qualification), limits,
                                        'literature-index-reranker')

    def score(self, query, texts):
        scored = self._reranker.score(query, list(texts))
        if any(scored.truncated):
            raise ModelError('a passage does not fit beside the query; the index must split it, never truncate')
        return list(scored.scores)


def index_models(embedder, reranker, *, embedding_qualification, reranker_qualification):
    """The (embedding, reranker) adapters an index build and its provider use; refuses unqualified models."""
    return (IndexEmbedder(embedder, reranker, qualification=embedding_qualification),
            IndexReranker(reranker, embedder.model, qualification=reranker_qualification))


# ---------------------------------------------------------------- command line

def _loaded(model_id, *, root, threads, doc, tokenizer_factory):
    model = model_entry(model_id, doc=doc)
    kind = Embedder if model['role'] == 'embedding' else Reranker
    return kind(model_id, root=root, threads=threads, doc=doc, tokenizer_factory=tokenizer_factory)


def main(argv=None, *, doc=None, opener=None, tokenizer_factory=None) -> int:
    """``ravel literature models inspect|prefetch|qualify``; JSON on stdout.

    Only ``prefetch`` may use the network, through the installer's fetcher.
    ``inspect`` reads only and exits 1 when a default model is not completely
    installed; ``qualify`` loads verified files only, exits 1 when any report
    fails and 2 when a model is absent or altered. Nothing downloads implicitly.
    ``doc``, ``opener`` and ``tokenizer_factory`` are trusted test seams.
    """
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog='ravel literature models', description=main.__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('inspect', 'prefetch', 'qualify'):
        sub = commands.add_parser(name)
        if name != 'inspect':
            sub.add_argument('model_ids', nargs='*', metavar='MODEL_ID')
        sub.add_argument('--root', type=Path, default=None, help='model root (default: the per-user model root)')
        if name == 'qualify':
            sub.add_argument('--threads', type=int, default=None)
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else default_root()
    try:
        if args.command == 'inspect':
            result = inspect(root=root, doc=doc)
            defaults = set(result['defaults'].values())
            code = 0 if all(m['complete'] for m in result['models'] if m['model_id'] in defaults) else 1
        elif args.command == 'prefetch':
            result, code = prefetch(args.model_ids or None, root=root, opener=opener, doc=doc), 0
        else:
            ids = args.model_ids or sorted(set(_doc(doc)['defaults'].values()))
            result = [qualify(_loaded(i, root=root, threads=args.threads, doc=doc,
                                      tokenizer_factory=tokenizer_factory)) for i in ids]
            code = 0 if all(r['passed'] for r in result) else 1
    except ModelError as exc:
        print(f'ravel literature models: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return code
