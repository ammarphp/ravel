"""Paired retrieval benchmark runner: one index per embedding model, every question through governed search.

The runner compiles one located corpus (an admitted build record's products, or an
already compiled corpus), builds one pinned index per embedding model with the
qualified local models (the pinned reranker stays on for every arm), and sends every
question text, verbatim, through the governed serving ``search`` (hybrid mode). It
writes one JSONL run file per model in the registered arm format (one line per
question and replicate, with the served envelope), the cold and warm search latency,
process CPU time and peak memory, index build time, and a manifest of every digest:
models, reranker, index manifests, corpus, questions, settings and code.

Scoring is not part of the product: an external scorer consumes the run files. The
runner reads only question identifiers and texts; a question file carrying answer
material is refused. Nothing is fetched: absent or altered model assets refuse.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import sys
import time

KIND = 'literature-benchmark-run'
QUESTION_FIELDS = frozenset({'id', 'text', 'stratum', 'frozen_scope'})
DEFAULT_ARM = 'R-rerank'
USAGE = {'model_calls': 0, 'input_tokens': 0, 'output_tokens': 0}  # local models make no generative call
CODE = ('literature_benchmark.py', 'literature_index.py', 'literature_serving.py', 'literature_models.py',
        'literature_build.py', 'literature_provider.py')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def load_questions(path):
    """``[(id, text)]`` from an arm-facing question file; answer material is refused, never read."""
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    items = value.get('items') if isinstance(value, dict) else value
    if not isinstance(items, list) or not items:
        raise ValueError('question file must hold a nonempty items list')
    rows, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or set(item) - QUESTION_FIELDS or not {'id', 'text'} <= set(item):
            raise ValueError('question items carry only id, text, stratum and frozen_scope')
        if not isinstance(item['id'], str) or not item['id'] or item['id'] in seen:
            raise ValueError('unique question ids required')
        if not isinstance(item['text'], str) or not item['text'].strip():
            raise ValueError('question text required')
        seen.add(item['id'])
        rows.append((item['id'], item['text']))
    return rows, {'path': str(Path(path).resolve()), 'sha256': _sha(raw), 'size': len(raw), 'questions': len(rows)}


def pinned_models(model_id, *, reranker_id=None, root=None, threads=None):
    """The qualified index adapters of one embedding model and the pinned reranker; offline only."""
    from . import literature_models as lm
    embedder = lm.Embedder(model_id, root=root, threads=threads)
    reranker = lm.Reranker(reranker_id, root=root, threads=threads)
    return lm.index_models(embedder, reranker, embedding_qualification=lm.qualify(embedder),
                           reranker_qualification=lm.qualify(reranker))


def _percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return None
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _latency(lines):
    cold = [l['latency_seconds'] for l in lines if l['cache'] == 'cold']
    warm = [l['latency_seconds'] for l in lines if l['cache'] == 'warm']
    return {'cold_seconds': cold[0] if cold else None, 'warm_count': len(warm),
            'warm_p50_seconds': _percentile(warm, 0.5), 'warm_p95_seconds': _percentile(warm, 0.95),
            'all_p50_seconds': _percentile(cold + warm, 0.5), 'all_p95_seconds': _percentile(cold + warm, 0.95),
            'law': 'nearest-rank percentiles; the first search after the index load is cold'}


def _peak_rss_bytes():
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == 'darwin' else peak * 1024)


def _status(reply):
    if reply['status'] == 'ok':
        return 'ok'
    code = (reply.get('error') or {}).get('code')
    if code == 'budget_exhausted':
        return 'timeout'
    return 'error' if code in ('provider_failed', 'provider_schema_violation', 'output_failed') else 'refused'


def _compile_corpus(admission, corpus, base_dir, receipt_ids, excluded_roots):
    from . import literature_index
    if (admission is None) == (corpus is None):
        raise ValueError('one admitted build record or one compiled corpus is required')
    if corpus is not None:
        raw = Path(corpus).read_bytes()
        return literature_index.validate_corpus(json.loads(raw)), {'path': str(Path(corpus).resolve()),
                                                                   'sha256': _sha(raw), 'kind': 'corpus'}
    raw = Path(admission).read_bytes()
    record = json.loads(raw)
    if not isinstance(record, dict) or not isinstance(record.get('products'), list):
        raise ValueError('an admitted build record with products is required')
    compiled = literature_index.corpus_from_products(
        record['products'], base_dir=base_dir, receipt_ids=receipt_ids or {},
        bibliography=record.get('bibliography', ()), excluded_roots=list(excluded_roots) or None)
    return compiled, {'path': str(Path(admission).resolve()), 'sha256': _sha(raw), 'kind': 'build-admission'}


def _arm(model_id, default_model, arm_prefix):
    return arm_prefix if model_id == default_model else arm_prefix + '@' + model_id


def run(*, questions, out, base_dir, model_ids, admission=None, corpus=None, receipt_ids=None, reranker_id=None,
        models_root=None, threads=None, top_k=20, budget_bytes=131072, max_seconds=30.0, replicates=1,
        excluded_roots=(), excluded_origins=None, arm_prefix=DEFAULT_ARM, default_model=None, adapters=None,
        clock=time.perf_counter):
    """Run every question once per replicate against one index per model; return the manifest.

    ``adapters(model_id)`` returns ``(embedding adapter, reranker adapter)`` (default: the
    qualified pinned models from ``models_root``, see ``pinned_models``). ``base_dir`` holds
    the admitted originals the served excerpts are authenticated against.
    """
    from . import broker as core, knowledge_broker, literature_build, literature_index, literature_serving
    from . import literature_models, literature_settings
    origins = (literature_settings.configured_excluded_origins() if excluded_origins is None
               else literature_index.normalize_excluded_origins(excluded_origins))
    if not model_ids or len(set(model_ids)) != len(model_ids):
        raise ValueError('distinct embedding model ids required')
    if type(replicates) is not int or not 1 <= replicates <= 10 or type(top_k) is not int or not 1 <= top_k <= 64:
        raise ValueError('bounded replicates and top_k required')
    rows, question_pin = load_questions(questions)
    out = Path(out).absolute()
    if out.exists():
        raise ValueError('fresh benchmark output directory required')
    (out / 'runs').mkdir(parents=True)
    base_dir = Path(base_dir).absolute()
    compiled, corpus_pin = _compile_corpus(admission, corpus, base_dir, receipt_ids, excluded_roots)
    literature_build._origin_exclusion(compiled, origins)
    default_model = default_model or literature_models.catalogue()['defaults']['embedding']
    adapters = adapters or (lambda model_id: pinned_models(model_id, reranker_id=reranker_id, root=models_root,
                                                          threads=threads))
    budgets = {'max_tokens': budget_bytes, 'max_bytes': budget_bytes, 'max_seconds': max_seconds,
               'max_expansions': 4096}
    requests = len(rows) * replicates
    manifest = {'schema_version': 1, 'kind': KIND, 'questions': question_pin, 'corpus': corpus_pin,
                'corpus_sha256': literature_index.digest(compiled),
                'settings': {'mode': 'hybrid', 'top_k': top_k, 'budgets': budgets, 'replicates': replicates,
                             'reranker': 'on', 'query': 'question text verbatim', 'threads': threads,
                             'default_model': default_model, 'arm_prefix': arm_prefix},
                'code': {name: _sha((Path(__file__).parent / name).read_bytes()) for name in CODE},
                'platform': {'system': platform.system(), 'machine': platform.machine(),
                             'python': platform.python_version(), 'cpu_count': os.cpu_count()},
                'models': {}, 'scoring': 'external; this runner reads no gold'}
    manifest['settings_sha256'] = _sha(_canonical(manifest['settings']))
    for model_id in model_ids:
        arm = _arm(model_id, default_model, arm_prefix)
        load_start = clock()
        embedding, reranking = adapters(model_id)
        loaded = clock() - load_start
        build_start, build_cpu = clock(), time.process_time()
        snapshot = literature_build.build_index(out / 'indexes' / model_id, compiled, embedder=embedding,
                                                reranker_identity=reranking.identity, excluded_roots=excluded_roots,
                                                source_root=base_dir, excluded_origins=origins)
        build_seconds, build_cpu = clock() - build_start, time.process_time() - build_cpu
        provider = literature_index.HybridLiteratureProvider(snapshot, embedder=embedding, reranker=reranking,
                                                             cursor_key=hashlib.sha256(b'benchmark' + model_id.encode()).digest())
        configuration = literature_serving.Serving(
            provider, snapshot=snapshot, qualification=literature_serving.qualify(provider, snapshot),
            source_root=base_dir, index_root=out / 'indexes' / model_id, excluded_origins=origins,
            ceilings={'max_tokens': max(budget_bytes, 131072), 'max_bytes': max(budget_bytes, 131072),
                      'max_seconds': max(max_seconds, 60.0), 'max_expansions': 4096, 'max_results': 64},
            allowance={'max_requests': requests + 1, 'max_bytes': (requests + 1) * max(budget_bytes, 131072),
                       'max_seconds': (requests + 1) * max(max_seconds, 60.0)})
        run_dir = out / 'serving' / model_id
        (run_dir / 'inputs').mkdir(parents=True)
        (run_dir / 'inputs' / 'task_contract.json').write_text(json.dumps({'forbidden_sources': []}))
        workspace = core.work_root(run_dir) / 'benchmark' / '1'
        for name in ('inputs', 'outputs', 'scratch', 'calls'):
            (workspace / name).mkdir(parents=True)
        broker = knowledge_broker.create(run_dir, workspace, role='literature-scout', node_id='benchmark',
                                         attempt=1, allowed_actions=[literature_serving.ACTION],
                                         max_calls=requests + 8)
        literature_serving.register(broker, configuration)
        lines, cpu_start = [], time.process_time()
        for replicate in range(1, replicates + 1):
            for question_id, text in rows:
                cache = 'cold' if not lines else 'warm'
                arguments = {'query': text, 'top_k': top_k, 'mode': 'hybrid', 'document_scope': [], 'filters': {},
                             'budgets': budgets}
                start = clock()
                try:
                    reply = literature_serving.call(broker, 'search', arguments)
                    status = _status(reply)
                    envelope = json.loads(literature_serving.load(run_dir, reply)) if status == 'ok' else None
                    error = None if status == 'ok' else (reply.get('error') or {}).get('code')
                except (OSError, ValueError) as exc:
                    status, envelope, error = 'error', None, type(exc).__name__
                line = {'arm': arm, 'question_id': question_id, 'replicate': replicate, 'status': status,
                        'latency_seconds': round(clock() - start, 6), 'cache': cache, 'usage': dict(USAGE)}
                if envelope is not None:
                    line['envelope'] = envelope
                if error is not None:
                    line['error'] = error
                lines.append(line)
        search_cpu = time.process_time() - cpu_start
        path = out / 'runs' / (arm.replace('@', '__') + '.jsonl')
        raw = b''.join(_canonical(line) + b'\n' for line in lines)
        path.write_bytes(raw)
        statuses = [l['status'] for l in lines]
        manifest['models'][model_id] = {
            'arm': arm, 'embedding': deepcopy(embedding.identity), 'reranker': deepcopy(reranking.identity),
            'index': {'id': snapshot['manifest']['id'], 'manifest_sha256': snapshot['manifest']['manifest_sha256'],
                      'units': snapshot['manifest']['unit_count'], 'dimensions': snapshot['manifest']['dimensions']},
            'run_file': {'path': str(path), 'sha256': _sha(raw), 'lines': len(lines)},
            'status': {s: statuses.count(s) for s in sorted(set(statuses))},
            'latency': _latency(lines), 'model_load_seconds': round(loaded, 6),
            'build_seconds': round(build_seconds, 6), 'build_cpu_seconds': round(build_cpu, 6),
            'search_cpu_seconds': round(search_cpu, 6), 'peak_rss_bytes': _peak_rss_bytes(),
            'peak_rss_scope': 'process peak so far; run one model per process for a per-model figure'}
    (out / 'manifest.json').write_bytes(json.dumps(manifest, indent=2, sort_keys=True).encode() + b'\n')
    return manifest


def main(argv=None):
    """``ravel literature benchmark``: the paired run files and manifest; scoring stays external."""
    parser = argparse.ArgumentParser(prog='ravel literature benchmark', description=main.__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--admission', type=Path, help='admitted build record (products and bibliography)')
    source.add_argument('--corpus', type=Path, help='an already compiled located corpus')
    parser.add_argument('--base-dir', type=Path, required=True, help='root of the admitted originals')
    parser.add_argument('--receipts', type=Path, help='JSON object of trusted receipt ids keyed by sha256')
    parser.add_argument('--questions', type=Path, required=True, help='arm-facing questions: items of id and text')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model', action='append', required=True, help='embedding model id (repeatable)')
    parser.add_argument('--reranker', default=None, help='reranker model id (default: the pinned default)')
    parser.add_argument('--root', type=Path, default=None, help='literature model root')
    parser.add_argument('--threads', type=int, default=None)
    parser.add_argument('--top-k', type=int, default=20)
    parser.add_argument('--budget-bytes', type=int, default=131072)
    parser.add_argument('--replicates', type=int, default=1)
    parser.add_argument('--excluded-root', action='append', default=[])
    parser.add_argument('--arm-prefix', default=DEFAULT_ARM)
    args = parser.parse_args(argv)
    try:
        receipts = json.loads(args.receipts.read_text()) if args.receipts else None
        manifest = run(questions=args.questions, out=args.out, base_dir=args.base_dir, model_ids=args.model,
                       admission=args.admission, corpus=args.corpus, receipt_ids=receipts,
                       reranker_id=args.reranker, models_root=args.root, threads=args.threads, top_k=args.top_k,
                       budget_bytes=args.budget_bytes, replicates=args.replicates,
                       excluded_roots=args.excluded_root, arm_prefix=args.arm_prefix)
    except (OSError, ValueError) as exc:
        print(f'ravel literature benchmark: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({k: manifest[k] for k in ('kind', 'questions', 'corpus_sha256', 'settings_sha256')}
                     | {'models': {m: {k: v[k] for k in ('arm', 'run_file', 'status', 'latency', 'build_seconds')}
                                   for m, v in manifest['models'].items()}}, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
