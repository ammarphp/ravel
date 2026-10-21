"""Deterministic, atomic storage for local literature embeddings.

Adapters own inference. This module owns validated immutable snapshots and a
bounded restart journal; a failed build never advances the current pointer.
An embedding adapter that declares a token window (``token_window`` and
``passage_tokens``) has every unit split to fit it before embedding; its
identity, recorded in the manifest, binds the model assets and qualification.
A build given ``excluded_roots`` refuses any corpus member or index under one.
A build given ``excluded_origins`` refuses, before any split, embedding or write,
a corpus whose papers, units or inputs descend from an excluded origin (by
document, pin, run or path, through their lineage) or whose derived rows name
no ancestry; its manifest records the excluded-origin digest, so a changed set
makes the index stale.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile

from . import state_io

MAX_BYTES = 512 * 1024 * 1024
MAX_UNITS = 100000
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _canonical(value):
    def check(item):
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                check(child)
            return
        if type(item) is dict and all(type(k) is str for k in item):
            for child in item.values():
                check(child)
            return
        raise ValueError("invalid literature JSON value")
    try:
        check(value)
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode("utf-8")
        if len(data) > MAX_BYTES:
            raise ValueError()
        return data
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        raise ValueError("invalid or oversized literature JSON") from None


def _hash(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _identity(value):
    if type(value) is not dict or not value:
        raise ValueError("literature adapter identity must be a nonempty JSON object")
    _canonical(value)
    return deepcopy(value)


def _safe(path):
    absolute = path.absolute()
    if any(part.is_symlink() for part in (absolute, *absolute.parents)):
        raise ValueError("symlinked literature storage is forbidden")


def _directory(path):
    _safe(path)
    if path.exists() and not path.is_dir():
        raise ValueError("invalid literature storage directory")


def _read(path):
    _safe(path)
    try:
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise ValueError()
        value = state_io.read_json(path)
        _canonical(value)
        return value
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("invalid literature storage JSON") from None


def _write(path, value):
    value = json.loads(_canonical(value))
    if len((json.dumps(value, indent=2, allow_nan=False) + "\n").encode("utf-8")) > MAX_BYTES:
        raise ValueError("oversized literature storage JSON")
    _safe(path)
    state_io.atomic_json(path, value)


def _vectors(values, count, dimensions=None):
    if type(values) is not list or len(values) != count:
        raise ValueError("invalid literature embedding count")
    result = []
    width = dimensions
    for row in values:
        if type(row) is not list or not row or any(
            type(x) not in (int, float) for x in row
        ):
            raise ValueError("invalid literature embedding vector")
        try:
            vector = [float(x) for x in row]
        except (OverflowError, ValueError):
            raise ValueError("invalid literature embedding vector") from None
        if (not all(math.isfinite(x) for x in vector)
                or not any(x != 0 for x in vector) or not math.isfinite(math.hypot(*vector))):
            raise ValueError("invalid literature embedding vector")
        if width is None:
            width = len(vector)
        if len(vector) != width:
            raise ValueError("inconsistent literature embedding dimensions")
        result.append(vector)
    if count == 0 and dimensions not in (None, 0):
        raise ValueError("invalid empty literature embedding dimensions")
    _canonical(result)
    return result, width or 0


def _corpus(value):
    from .literature_index import validate_corpus
    try:
        result = validate_corpus(value)
        _canonical(result)
        if len(result['units']) > MAX_UNITS:
            raise ValueError()
        return result
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError("invalid literature corpus") from None


def _settings(value):
    from .literature_index import normalize_settings
    try:
        result = normalize_settings(value)
        _canonical(result)
        return result
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError("invalid literature index settings") from None


def _root(root):
    root = Path(root)
    _directory(root)
    for name in ('snapshots', 'staging'):
        _directory(root / name)
    _safe(root / 'current.json')
    _safe(root / 'build.lock')
    return root


def _id(value):
    if type(value) is not str or not _HEX.fullmatch(value):
        raise ValueError("invalid literature snapshot id")
    return value


def load_index(root, snapshot_id=None):
    """Load one pinned snapshot; the current pointer is captured exactly once."""
    root = _root(root)
    if snapshot_id is None:
        pointer = _read(root / 'current.json')
        if type(pointer) is not dict or set(pointer) != {'id'}:
            raise ValueError("invalid literature current pointer")
        snapshot_id = pointer['id']
    identity = _id(snapshot_id)
    directory = root / 'snapshots' / identity
    _directory(directory)
    manifest = _read(directory / 'manifest.json')
    corpus = _read(directory / 'corpus.json')
    vectors = _read(directory / 'vectors.json')
    return validate_snapshot({'manifest': manifest, 'corpus': corpus, 'vectors': vectors}, snapshot_id=identity)


def validate_snapshot(snapshot, *, snapshot_id=None):
    """Verify a detached in-memory snapshot with the same contract as disk reads."""
    if type(snapshot) is not dict or set(snapshot) != {'manifest', 'corpus', 'vectors'}:
        raise ValueError("invalid literature snapshot")
    _canonical(snapshot)
    snapshot = deepcopy(snapshot)
    manifest, corpus, vectors = (snapshot[k] for k in ('manifest', 'corpus', 'vectors'))
    if type(manifest) is not dict:
        raise ValueError("invalid literature manifest")
    identity = _id(manifest.get('manifest_sha256'))
    if snapshot_id is not None and _id(snapshot_id) != identity:
        raise ValueError("invalid literature snapshot identity")
    keys = {'schema_version', 'kind', 'corpus_sha256', 'vectors_sha256', 'embedding',
            'reranker', 'settings', 'unit_count', 'dimensions', 'id', 'manifest_sha256'}
    if type(manifest) is not dict or set(manifest) - {'excluded_origins_sha256'} != keys:
        raise ValueError("invalid literature manifest")
    if 'excluded_origins_sha256' in manifest and not _HEX.fullmatch(str(manifest['excluded_origins_sha256'])):
        raise ValueError("invalid literature manifest excluded-origin digest")
    content = {key: value for key, value in manifest.items() if key not in ('id', 'manifest_sha256')}
    if (_hash(content) != identity or manifest['manifest_sha256'] != identity
            or manifest['id'] != 'literature:' + identity
            or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
            or manifest['kind'] != 'literature-index-manifest'):
        raise ValueError("invalid literature manifest identity")
    _identity(manifest['embedding'])
    _identity(manifest['reranker'])
    if _canonical(_settings(manifest['settings'])) != _canonical(manifest['settings']):
        raise ValueError("invalid literature manifest settings")
    validated = _corpus(corpus)
    if _canonical(validated) != _canonical(corpus):
        raise ValueError("noncanonical literature corpus")
    if (type(manifest['unit_count']) is not int or manifest['unit_count'] != len(corpus['units'])
            or type(manifest['dimensions']) is not int or manifest['dimensions'] < 0):
        raise ValueError("invalid literature manifest counts")
    _vectors(vectors, manifest['unit_count'], manifest['dimensions'])
    if _hash(corpus) != manifest['corpus_sha256'] or _hash(vectors) != manifest['vectors_sha256']:
        raise ValueError("invalid literature snapshot data hash")
    return deepcopy({'manifest': manifest, 'corpus': corpus, 'vectors': vectors})


def _journal(key, entries):
    content = {'key': key, 'embeddings': entries}
    return dict(content, journal_sha256=_hash(content))


def _cache_key(embedding, unit):
    return _hash({'embedding': embedding, 'unit': unit})


def _discard_journal(directory):
    """A published snapshot holds every vector; its restart journal is redundant."""
    _safe(directory)
    if directory.exists():
        shutil.rmtree(directory)


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _exclusion(root, corpus, excluded_roots, source_root):
    """Refuse a build naming any path under a declared excluded root, before reading or embedding."""
    from .literature_index import corpus_paths, excluded, normalize_excluded_roots
    roots = normalize_excluded_roots(excluded_roots)
    if not roots:
        return
    if source_root is None or not Path(source_root).is_absolute():
        raise ValueError("an excluded-root build requires its absolute corpus source root")
    if excluded(Path(root).absolute(), roots) or excluded(Path(source_root), roots):
        raise ValueError("literature index or corpus root lies under an excluded root")
    paths = corpus_paths(corpus)
    if any(type(path) is not str or excluded(path, roots, source_root) for path in paths):
        raise ValueError("a literature corpus member lies under an excluded root")


def _split(corpus, embedder):
    window, count = getattr(embedder, 'token_window', None), getattr(embedder, 'passage_tokens', None)
    if window is None and count is None:
        return corpus
    if type(window) is not int or window < 1 or not callable(count):
        raise ValueError("literature embedding token window must be explicit")
    from .literature_index import split_units
    try:
        return _corpus(split_units(corpus, count=count, limit=window))
    except ValueError as exc:
        raise ValueError("literature units cannot fit the embedding token window: " + str(exc)[:512]) from None


def _origin_exclusion(corpus, excluded_origins):
    """Refuse a corpus descending from an excluded origin, or with derived rows lacking ancestry."""
    from .literature_index import normalize_excluded_origins, origin_problems
    if excluded_origins is None:
        from .literature_settings import configured_excluded_origins
        origins = configured_excluded_origins()
    else:
        origins = normalize_excluded_origins(excluded_origins)
    if origins:
        named, orphans = origin_problems(corpus, origins)
        if named or orphans:
            raise ValueError(f"literature corpus refused: {named} row(s) descend from an excluded origin and "
                             f"{orphans} derived row(s) name no ancestry; nothing was embedded or written")
    return origins


def _build(root, corpus, *, embedder, reranker_identity, settings, resume, batch_size, update,
           excluded_roots=None, source_root=None, excluded_origins=None):
    if type(batch_size) is not int or not 1 <= batch_size <= MAX_UNITS:
        raise ValueError("invalid literature build batch size")
    corpus = _corpus(corpus)
    _exclusion(root, corpus, excluded_roots, source_root)
    origins = _origin_exclusion(corpus, excluded_origins)
    corpus = _split(corpus, embedder)
    embedding = _identity(embedder.identity)
    reranker = _identity(reranker_identity)
    settings = _settings(settings)
    signature = dict(corpus_sha256=_hash(corpus), embedding=embedding, reranker=reranker, settings=settings)
    if origins:
        from .literature_index import excluded_origins_sha256
        signature['excluded_origins_sha256'] = excluded_origins_sha256(origins)
    key = _hash(signature)
    root = _root(root)
    root.mkdir(parents=True, exist_ok=True)
    with state_io.file_lock(root / 'build.lock'):
        _root(root)
        snapshots = root / 'snapshots'
        staging = root / 'staging'
        snapshots.mkdir(exist_ok=True)
        staging.mkdir(exist_ok=True)
        # A previously completed matching build needs no adapter invocation.
        for directory in sorted(snapshots.iterdir()):
            _safe(directory)
            if not _HEX.fullmatch(directory.name):
                continue
            manifest = _read(directory / 'manifest.json')
            if (type(manifest) is dict
                    and manifest.get('excluded_origins_sha256') == signature.get('excluded_origins_sha256')
                    and all(_canonical(manifest.get(k)) == _canonical(v) for k, v in signature.items())):
                result = load_index(root, directory.name)
                _write(root / 'current.json', {'id': directory.name})
                _discard_journal(staging / key)
                return result
        units = corpus['units']
        unit_keys = [_cache_key(embedding, unit) for unit in units]
        allowed = set(unit_keys)
        directory = staging / key
        _directory(directory)
        directory.mkdir(exist_ok=True)
        journal_path = directory / 'progress.json'
        cache = {}
        if resume and journal_path.exists():
            journal = _read(journal_path)
            if (type(journal) is not dict or set(journal) != {'key', 'embeddings', 'journal_sha256'}
                    or journal['key'] != key or type(journal['embeddings']) is not list
                    or len(journal['embeddings']) > len(allowed)
                    or journal['journal_sha256'] != _hash({
                        'key': journal['key'], 'embeddings': journal['embeddings']})):
                raise ValueError("invalid literature progress journal")
            for entry in journal['embeddings']:
                if (type(entry) is not dict or set(entry) != {'key', 'vector'}
                        or type(entry['key']) is not str or entry['key'] not in allowed
                        or entry['key'] in cache):
                    raise ValueError("invalid literature progress entry")
                cache[entry['key']] = _vectors([entry['vector']], 1)[0][0]
            _vectors(list(cache.values()), len(cache))
        elif not resume:
            _write(journal_path, _journal(key, []))
        if update and (root / 'current.json').exists():
            previous = load_index(root)
            if _canonical(previous['manifest']['embedding']) == _canonical(embedding):
                for unit, vector in zip(previous['corpus']['units'], previous['vectors']):
                    old_key = _cache_key(embedding, unit)
                    if old_key in allowed:
                        if old_key in cache and cache[old_key] != vector:
                            raise ValueError("conflicting literature progress vector")
                        cache[old_key] = vector
        _vectors(list(cache.values()), len(cache))
        def save():
            _write(journal_path, _journal(key, [
                {'key': k, 'vector': cache[k]} for k in sorted(cache)]))
        save()
        missing = list(dict.fromkeys(k for k in unit_keys if k not in cache))
        by_key = dict(zip(unit_keys, units))
        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            try:
                raw = embedder.embed_documents([by_key[k]['indexed_text'] for k in batch])
            except Exception:
                raise ValueError("literature embedding adapter failed") from None
            if _canonical(_identity(embedder.identity)) != _canonical(embedding):
                raise ValueError("literature embedding identity changed during build")
            vectors, _ = _vectors(raw, len(batch))
            if cache:
                _vectors(vectors, len(batch), len(next(iter(cache.values()))))
            cache.update(zip(batch, vectors))
            save()
        vectors, dimensions = _vectors([cache[k] for k in unit_keys], len(units))
        content = dict(schema_version=1, kind='literature-index-manifest', **signature,
                       vectors_sha256=_hash(vectors), unit_count=len(units), dimensions=dimensions)
        identity = _hash(content)
        manifest = dict(content, id='literature:' + identity, manifest_sha256=identity)
        validate_snapshot({'manifest': manifest, 'corpus': corpus, 'vectors': vectors})
        destination = snapshots / identity
        _directory(destination)
        if destination.exists():
            result = load_index(root, identity)
        else:
            temporary = Path(tempfile.mkdtemp(prefix='.build-', dir=snapshots))
            try:
                for filename, value in (('manifest.json', manifest), ('corpus.json', corpus), ('vectors.json', vectors)):
                    _write(temporary / filename, value)
                validate_snapshot({
                    'manifest': _read(temporary / 'manifest.json'),
                    'corpus': _read(temporary / 'corpus.json'),
                    'vectors': _read(temporary / 'vectors.json')})
                _fsync_directory(temporary)
                os.rename(temporary, destination)
                _fsync_directory(snapshots)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
            result = load_index(root, identity)
        _write(root / 'current.json', {'id': identity})
        _discard_journal(directory)
        return deepcopy(result)


def build_index(root, corpus, *, embedder, reranker_identity, settings=None, resume=False, batch_size=32,
                excluded_roots=None, source_root=None, excluded_origins=None):
    """Build and publish one snapshot.

    ``excluded_roots`` (absolute paths, from trusted installation settings) and
    ``source_root`` (the corpus pins' base) make the build refuse any member,
    corpus root or index root under an excluded root. ``excluded_origins``
    (``{kind, value}`` entries from the same settings) refuses a corpus that
    descends from one, and is recorded in the manifest by digest.
    """
    return _build(root, corpus, embedder=embedder, reranker_identity=reranker_identity,
                  settings=settings, resume=resume, batch_size=batch_size, update=False,
                  excluded_roots=excluded_roots, source_root=source_root, excluded_origins=excluded_origins)


def update_index(root, corpus, *, embedder, reranker_identity, settings=None, resume=False, batch_size=32,
                 excluded_roots=None, source_root=None, excluded_origins=None):
    """Replace the supplied corpus, reusing only exactly matching cached units."""
    return _build(root, corpus, embedder=embedder, reranker_identity=reranker_identity,
                  settings=settings, resume=resume, batch_size=batch_size, update=True,
                  excluded_roots=excluded_roots, source_root=source_root, excluded_origins=excluded_origins)
