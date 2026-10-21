"""Deep evidence scoring: question-conditioned relevance scores and summaries for retrieved passages.

This is an explicit, governed workflow step above the retrieval provider. The
provider's ``search`` stays free of model calls. This step takes an envelope the
provider already returned and asks a model, through recorded charged Graph calls,
to rate each top candidate's relevance to one question (an integer 0..10, where 0
means irrelevant) and to summarise what that passage says about it.

The mechanism follows the relevance-score and contextual-summary evidence step of
the Apache-2.0 ``paper-qa`` project. This is an independent implementation: no
upstream code, prompt text or dependency is used. Deliberate departures:

- Candidates can be batched, one call per ``batch_size`` passages, as well as
  scored one passage per call (``batch_size`` 1). The profile is recorded.
- The reply is a closed schema that the Host checks. Nothing here repairs,
  salvages or coerces a reply.
- Each call has one attempt and no hidden retry. A retry is a new explicit Graph.
- A failed, refused, missing or invalid call stays an error on each of its
  candidates. There is no default or fallback score, and no candidate is dropped.
- Every original located passage is returned unmodified beside its assessment.

Flow: ``request_document`` -> ``write_request`` -> ``graph_spec`` -> the caller's
``agent_graph.create`` and ``agent_graph.execute`` -> ``assemble``. The call
instructions are the protocol of a registered role card, never text written here,
so the step is unavailable until that card is registered. ``assemble`` records
calls, tokens and call latency per question. Scores and summaries are generated
reading aids: they are never evidence, an answer or a physics claim.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

from . import literature_provider

KIND = 'literature-evidence-scoring'
REQUEST_KIND = 'literature-evidence-scoring-request'
BATCH_KIND = 'literature-evidence-scoring-batch'
REPLY_KIND = 'literature-evidence-scoring-reply'
ROLE = 'literature-evidence-scorer'
INPUT_ID = 'scoring-batch'
GRAPH_ROLE = 'proposer'  # a reading aid, not a review: it claims no independence credit
SCORE_MIN, SCORE_MAX = 0, 10
LIMITS = {'top_k': 8, 'batch_size': 4, 'max_summary_chars': 600, 'max_passage_bytes': 8192}
BOUNDS = {'top_k': (1, 32), 'batch_size': (1, 8), 'max_summary_chars': (16, 2000), 'max_passage_bytes': (64, 65536)}
ADAPTERS = ('model', 'responses', 'command', 'external', 'anthropic', 'gemini', 'chat_completions')
MAX_QUESTION_CHARS = 2048
MAX_REQUEST_BYTES = 4 * 1024 * 1024
OUTPUT_TOKEN_BOUNDS = (64, 16384)
_ID = re.compile(r'^[a-z][a-z0-9-]{0,63}$')
_SHA = re.compile(r'^[0-9a-f]{64}$')


class _Refusal(ValueError):
    """A reason-coded refusal; the code is kept in the record, never replaced by a score."""
    def __init__(self, code, detail=''):
        super().__init__(code + (': ' + detail if detail else ''))
        self.code = code


def _error(exc):
    """A refusal's cause in the Graph's node-error form; the reason code alone loses it."""
    return {'type': type(exc).__name__, 'message': str(exc)[:1000]}


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('nonfinite JSON number')


def _loads(raw):
    return json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)


def _bytes(document):
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def _keys(value, keys, what):
    if type(value) is not dict or set(value) != set(keys):
        raise ValueError(f'{what} requires exactly: ' + ', '.join(sorted(keys)))


def _question(question):
    if type(question) is not str or not question.strip() or len(question) > MAX_QUESTION_CHARS:
        raise ValueError(f'question must be nonblank text of at most {MAX_QUESTION_CHARS} characters')
    return question


def _limits(limits):
    merged = dict(LIMITS)
    if limits is not None:
        if type(limits) is not dict or set(limits) - set(LIMITS):
            raise ValueError('scoring limits accept only: ' + ', '.join(sorted(LIMITS)))
        merged.update(limits)
    for key, (low, high) in BOUNDS.items():
        if type(merged[key]) is not int or not low <= merged[key] <= high:
            raise ValueError(f'{key} must be an integer in {low}..{high}')
    return merged


def _card_instructions(role, roles=None):
    """The registered card's protocol, the only instruction source; ``roles`` is a registry document override."""
    from . import role_registry
    try:
        card = role_registry.load(role, document=roles)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise _Refusal('role_card_unavailable', str(exc)) from None
    protocol = card.get('protocol')
    if type(protocol) is not list or not protocol or any(type(p) is not str or not p.strip() for p in protocol):
        raise _Refusal('role_card_unavailable', 'a nonempty protocol is required: ' + str(role))
    return ' '.join(protocol)


def _batch_document(question, role, limits, rows, batch, batches):
    """The complete model input of one call: the question and its passages' exact located text."""
    return {'schema_version': 1, 'kind': BATCH_KIND, 'question': question, 'role': role, 'batch': batch,
            'batches': batches,
            'limits': {'score_min': SCORE_MIN, 'score_max': SCORE_MAX, 'max_summary_chars': limits['max_summary_chars']},
            'candidates': [{'candidate': row['id'], 'document_id': row['document_id'], 'version': row['version'],
                            'section_path': row['location']['section_path'],
                            'page_number': row['location']['page_number'], 'text': row['text']} for row in rows]}


def _project(question, search_request, envelope, role, limits):
    """Pure projection of one scoring request; it reads no file and makes no call."""
    question, limits = _question(question), _limits(limits)
    if type(role) is not str or not _ID.match(role):
        raise ValueError('registered role card ID required')
    request = literature_provider.validate_request(search_request)
    if type(envelope) is not dict:
        raise ValueError('a retrieval envelope object is required')
    # Structural conformance of the served envelope: exact excerpts, ranks, scope and budgets.
    envelope = literature_provider.validate_candidates(envelope, request, provider_id=envelope.get('provider_id'),
                                                       index=envelope.get('index'))
    rows = envelope['results']  # complete ordered ranks 1..n, validated above
    considered, skipped = [], []
    for position, row in enumerate(rows):
        if position >= limits['top_k']:
            skipped.append({'id': row['id'], 'reason': 'beyond_top_k'})
        elif len(row['text'].encode('utf-8')) > limits['max_passage_bytes']:
            # Never truncate evidence for the model: an oversized passage is reported, not cut.
            skipped.append({'id': row['id'], 'reason': 'passage_exceeds_bound'})
        else:
            considered.append(row)
    size = limits['batch_size']
    groups = [considered[start:start + size] for start in range(0, len(considered), size)]
    batches = [{'batch': number, 'candidates': [row['id'] for row in group],
                'sha256': _digest(_bytes(_batch_document(question, role, limits, group, number, len(groups))))}
               for number, group in enumerate(groups, 1)]
    return {'schema_version': 1, 'kind': REQUEST_KIND, 'question': question, 'role': role, 'limits': limits,
            'profile': 'per-passage' if size == 1 else 'batched', 'search_request': request, 'envelope': envelope,
            'envelope_sha256': _digest(literature_provider.canonical(envelope)), 'not_scored': skipped,
            'batches': batches}


def request_document(question, search_request, envelope, *, role=ROLE, limits=None, roles=None):
    """The complete input of one question's scoring: the served candidates, the profile and the card.

    ``search_request``/``envelope`` are the provider request and the envelope served for it.
    Candidates are the top ``top_k`` located results in provider rank order; later or
    oversized ones are listed in ``not_scored`` with a reason and still returned by ``assemble``.
    """
    document = _project(question, search_request, envelope, role, limits)
    _card_instructions(role, roles)
    return document


def _request(document):
    _keys(document, {'schema_version', 'kind', 'question', 'role', 'limits', 'profile', 'search_request', 'envelope',
                     'envelope_sha256', 'not_scored', 'batches'}, 'evidence scoring request')
    if type(document['schema_version']) is not int or document['schema_version'] != 1 or document['kind'] != REQUEST_KIND:
        raise ValueError('unsupported evidence scoring request')
    expected = _project(document['question'], document['search_request'], document['envelope'], document['role'],
                        document['limits'])
    if document != expected:
        raise ValueError('evidence scoring request differs from its candidate projection')
    return expected


def _batch_path(plan_path, batch):
    plan_path = Path(plan_path)
    return plan_path.with_name(f'{plan_path.stem}.batch-{batch:03d}.json')


def _node_id(batch):
    return f'score-{batch:03d}'


def write_request(path, document, *, roles=None):
    """Write fresh batch files and then the request, and return the request pin.

    Each batch file sits beside the request (``<stem>.batch-NNN.json``) and is one call's
    complete model input. An existing file or a symlinked path is refused.
    """
    document = _request(document)
    _card_instructions(document['role'], roles)
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ordinary request destination required')
    by_id = {row['id']: row for row in document['envelope']['results']}
    files = []
    for batch in document['batches']:
        rows = [by_id[identity] for identity in batch['candidates']]
        raw = _bytes(_batch_document(document['question'], document['role'], document['limits'], rows,
                                     batch['batch'], len(document['batches'])))
        files.append((_batch_path(path, batch['batch']), raw))
    for target in (path, *(target for target, _ in files)):
        if target.exists() or target.is_symlink():
            raise FileExistsError(str(target))
    path.parent.mkdir(parents=True, exist_ok=True)
    for target, raw in files:
        with target.open('xb') as stream:
            stream.write(raw)
    raw = _bytes(document)
    # The request file is written last: it commits a complete set of batch inputs.
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path.resolve()), 'sha256': _digest(raw), 'size': len(raw)}


def _read_request(pin):
    if type(pin) is not dict or type(pin.get('path')) is not str or not _SHA.match(str(pin.get('sha256'))):
        raise _Refusal('invalid_request_pin')
    path = Path(pin['path'])
    try:
        if path.stat().st_size > MAX_REQUEST_BYTES:
            raise _Refusal('request_pin_mismatch')
        raw = path.read_bytes()
    except OSError:
        raise _Refusal('request_unavailable') from None
    if _digest(raw) != pin['sha256']:
        raise _Refusal('request_pin_mismatch')
    try:
        return _request(_loads(raw))
    except (ValueError, TypeError, RecursionError):
        raise _Refusal('invalid_request') from None


def _reply_schema(batch, limits):
    return {'type': 'object', 'additionalProperties': False, 'required': ['kind', 'batch_sha256', 'assessments'],
            'properties': {
                'kind': {'type': 'string', 'const': REPLY_KIND},
                'batch_sha256': {'type': 'string', 'const': batch['sha256']},
                'assessments': {'type': 'array', 'minItems': len(batch['candidates']),
                                'maxItems': len(batch['candidates']), 'items': {
                                    'type': 'object', 'additionalProperties': False,
                                    'required': ['candidate', 'relevance_score', 'summary'], 'properties': {
                                        'candidate': {'type': 'string', 'enum': list(batch['candidates'])},
                                        'relevance_score': {'type': 'integer', 'minimum': SCORE_MIN,
                                                            'maximum': SCORE_MAX},
                                        'summary': {'type': 'string', 'maxLength': limits['max_summary_chars']}}}}}}


def graph_spec(request_pin, *, graph_id, model, reasoning_effort, adapter='model', max_output_tokens=None,
               max_wall_seconds=600, roles=None):
    """One bounded registered-role call per batch: one attempt each, no dependencies or reworks.

    ``max_output_tokens`` is the per-call reservation (default 512 + 512 per candidate of the
    largest batch). The budget is exactly one call per batch. The instructions are the request's
    registered role card protocol, rendered at build time.
    A governed seat may use the original role card's broker tools.
    """
    from . import agent_graph
    document = _read_request(request_pin)
    if not document['batches']:
        raise ValueError('nothing to score: the request has no candidate batch')
    instructions = _card_instructions(document['role'], roles)
    if adapter not in ADAPTERS:
        raise ValueError('existing configured model transport required')
    if any(type(v) is not str or not v.strip() for v in (model, reasoning_effort)):
        raise ValueError('explicit actual model/effort required')
    largest = max(len(batch['candidates']) for batch in document['batches'])
    per_call = min(OUTPUT_TOKEN_BOUNDS[1], 512 + 512 * largest) if max_output_tokens is None else max_output_tokens
    if type(per_call) is not int or not OUTPUT_TOKEN_BOUNDS[0] <= per_call <= OUTPUT_TOKEN_BOUNDS[1]:
        raise ValueError('scoring output token bound outside {}..{}'.format(*OUTPUT_TOKEN_BOUNDS))
    nodes = []
    for batch in document['batches']:
        path = _batch_path(request_pin['path'], batch['batch'])
        if not path.is_file() or _digest(path.read_bytes()) != batch['sha256']:
            raise _Refusal('batch_input_changed', 'scoring batch file differs from its request')
        nodes.append({'id': _node_id(batch['batch']), 'kind': 'model', 'role': GRAPH_ROLE, 'registry_role': ROLE,
                      'depends_on': [],
                      'inputs': [{'id': INPUT_ID, 'path': str(path.absolute()), 'sha256': batch['sha256']}],
                      'packet': None, 'action': adapter, 'max_attempts': 1,
                      'parameters': {'model': model, 'reasoning_effort': reasoning_effort,
                                     'max_output_tokens': per_call,
                                     'output_schema': _reply_schema(batch, document['limits']),
                                     'instructions': instructions}})
    spec = {'schema_version': 1, 'graph_id': graph_id,
            'budget': {'max_nodes': len(nodes), 'max_calls': len(nodes), 'max_output_tokens': per_call * len(nodes),
                       'max_wall_seconds': max_wall_seconds, 'max_reworks': 0},
            'nodes': nodes}
    agent_graph.validate(spec)
    return spec


def _reply(value, batch, limits):
    """Validate one recorded reply against its batch; return {candidate: (score, summary)}."""
    try:
        _keys(value, {'kind', 'batch_sha256', 'assessments'}, 'scoring reply')
    except ValueError:
        raise _Refusal('invalid_reply') from None
    if value['kind'] != REPLY_KIND or value['batch_sha256'] != batch['sha256']:
        raise _Refusal('other_batch')
    rows = value['assessments']
    if type(rows) is not list or len(rows) != len(batch['candidates']):
        raise _Refusal('invalid_reply')
    result = {}
    for row in rows:
        try:
            _keys(row, {'candidate', 'relevance_score', 'summary'}, 'assessment')
        except ValueError:
            raise _Refusal('invalid_reply') from None
        score, summary = row['relevance_score'], row['summary']
        if (row['candidate'] not in batch['candidates'] or row['candidate'] in result
                or type(score) is not int or not SCORE_MIN <= score <= SCORE_MAX
                or type(summary) is not str or len(summary) > limits['max_summary_chars']
                or (score > SCORE_MIN and not summary.strip())):
            raise _Refusal('invalid_reply')
        result[row['candidate']] = (score, summary)
    return result


_NODE_REASONS = {'pending': 'not_run', 'running': 'incomplete', 'failed': 'call_failed',
                 'ambiguous': 'ambiguous_call', 'cancelled': 'cancelled'}


def _calls(root, state, node_id):
    """The current attempt's call receipts: status, latency and reserved tokens, never bodies."""
    from .agent_graph import digest
    calls = []
    # A node this request does not declare has no calls here; the spec comparison refuses it.
    attempt = (state['nodes'].get(node_id) or {}).get('attempt_id')
    if attempt is None:
        return calls
    for call_id, known in sorted(state['calls'].items()):
        if known.get('node_id') != node_id or known.get('attempt_id') != attempt:
            continue
        path = root / 'calls' / (call_id + '.json')
        receipt = _loads(path.read_bytes()) if path.is_file() else None
        if receipt is None or receipt.get('call_id') != call_id or (
                known.get('receipt_sha256') is not None and digest(receipt) != known['receipt_sha256']):
            raise _Refusal('call_receipt_changed')
        elapsed = receipt.get('elapsed_seconds')
        calls.append({'call_id': call_id, 'kind': receipt.get('kind'), 'status': receipt.get('status'),
                      'elapsed_seconds': elapsed if type(elapsed) in (int, float) else None,
                      'output_tokens_reserved': receipt.get('output_tokens_reserved'),
                      'error_type': receipt.get('error_type')})
    return calls


def _call_summary(calls, usage=None, transport=None):
    usage = usage if type(usage) is dict else {}
    elapsed = [c['elapsed_seconds'] for c in calls if c['elapsed_seconds'] is not None]
    return {'calls': len(calls), 'call_ids': [c['call_id'] for c in calls],
            'statuses': [c['status'] for c in calls],
            'elapsed_seconds': sum(elapsed) if elapsed else None,
            'output_tokens_reserved': sum(c['output_tokens_reserved'] or 0 for c in calls),
            'input_tokens': usage.get('input_tokens'), 'output_tokens': usage.get('output_tokens'),
            'total_tokens': usage.get('total_tokens'),
            'requested_model': (transport or {}).get('requested_model'),
            'observed_model': (transport or {}).get('observed_model'),
            'error_types': [c['error_type'] for c in calls if c['error_type']]}


def _outcome(batch, status, reason=None, error=None, call=None, scores=None):
    return {'batch': batch['batch'], 'node_id': _node_id(batch['batch']), 'candidates': list(batch['candidates']),
            'status': status, 'reason': reason, 'error': error,
            'call': call if call is not None else _call_summary([]), 'scores': scores}


def _admit(document, request_pin, graph_root, roles, campaign_root=None):
    """Admit each batch's recorded reply or keep its reason-coded error; returns (outcomes, graph)."""
    from . import agent_graph
    from .research_cycle import _graph_result
    from .state_io import file_lock
    batches = document['batches']
    if graph_root is None:
        return [_outcome(b, 'error', 'not_run') for b in batches], None
    root = Path(graph_root).absolute()
    graph = {'root': str(root), 'graph_id': None, 'spec_sha256': None, 'status': 'refused', 'reason': None}

    def refuse_all(code, exc=None):
        graph['reason'] = code
        return [_outcome(b, 'error', code, None if exc is None else _error(exc)) for b in batches], graph

    if not (root / agent_graph.SPEC).is_file() or not (root / agent_graph.STATE).is_file():
        return refuse_all('graph_result_unavailable')
    try:
        with file_lock(root / 'state.lock'):
            spec, state = agent_graph._load(root)
            calls = {b['batch']: _calls(root, state, _node_id(b['batch'])) for b in batches}
    except _Refusal as refusal:
        return refuse_all(refusal.code, refusal)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        return refuse_all('graph_result_unavailable', exc)
    graph.update(graph_id=spec.get('graph_id'), spec_sha256=agent_graph.digest(spec))
    try:
        node = spec['nodes'][0]
        expected = graph_spec(request_pin, graph_id=spec['graph_id'], model=node['parameters']['model'],
                              reasoning_effort=node['parameters']['reasoning_effort'], adapter=node['action'],
                              max_output_tokens=node['parameters']['max_output_tokens'],
                              max_wall_seconds=spec['budget']['max_wall_seconds'], roles=roles)
    except _Refusal as refusal:
        return refuse_all(refusal.code, refusal)
    except (ValueError, KeyError, IndexError, TypeError, OSError) as exc:
        return refuse_all('graph_spec_mismatch', exc)
    from .research_cycle import matches_campaign_graph
    try:
        matches = matches_campaign_graph(campaign_root, root, spec, expected)
    except (ValueError, KeyError, TypeError, OSError):
        matches = False
    if not matches:
        return refuse_all('graph_spec_mismatch')
    graph.update(status='admitted', reason=None)
    outcomes = []
    for batch in batches:
        node_id = _node_id(batch['batch'])
        current = state['nodes'][node_id]
        receipts = calls[batch['batch']]
        error = deepcopy(current.get('error'))
        if state['cancelled']:
            outcomes.append(_outcome(batch, 'error', 'graph_cancelled', error, _call_summary(receipts)))
            continue
        if current['status'] != 'completed':
            outcomes.append(_outcome(batch, 'error', _NODE_REASONS.get(current['status'], 'incomplete'), error,
                                     _call_summary(receipts)))
            continue
        try:
            origin = _graph_result(root, node_id)
        except (ValueError, KeyError, TypeError, OSError) as exc:
            outcomes.append(_outcome(batch, 'error', 'graph_result_unavailable', _error(exc), _call_summary(receipts)))
            continue
        value = origin['value']
        if origin['node_kind'] != 'model' or type(value) is not dict or value.get('kind') != 'model_result':
            outcomes.append(_outcome(batch, 'error', 'not_a_model_result', None, _call_summary(receipts)))
            continue
        call = _call_summary(receipts, value.get('usage'), value.get('transport'))
        call['receipt'] = deepcopy(origin['receipt'])
        try:
            scores = _reply(value.get('value'), batch, document['limits'])
        except _Refusal as refusal:
            outcomes.append(_outcome(batch, 'error', refusal.code, None, call))
            continue
        outcomes.append(_outcome(batch, 'admitted', None, None, call, scores))
    return outcomes, graph


def _usage(outcomes):
    """Per-question calls, tokens and call latency. Unknown token usage stays unknown, never zero."""
    statuses = [status for o in outcomes for status in o['call']['statuses']]
    tokens, unknown = {'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0}, 0
    for outcome in outcomes:
        call = outcome['call']
        if not call['calls']:
            continue
        if any(call[key] is None for key in tokens):
            unknown += 1
        for key in tokens:
            tokens[key] += call[key] or 0
    elapsed = [o['call']['elapsed_seconds'] for o in outcomes if o['call']['elapsed_seconds'] is not None]
    return {'batches': len(outcomes), 'calls': len(statuses),
            'completed_calls': statuses.count('completed'), 'failed_calls': statuses.count('failed'),
            'ambiguous_calls': statuses.count('ambiguous'),
            'other_calls': len(statuses) - sum(statuses.count(s) for s in ('completed', 'failed', 'ambiguous')),
            **tokens, 'tokens_complete': unknown == 0, 'calls_without_token_usage': unknown,
            'call_seconds': sum(elapsed), 'max_call_seconds': max(elapsed) if elapsed else None,
            'reserved_output_tokens': sum(o['call']['output_tokens_reserved'] for o in outcomes)}


def assemble(request_pin, graph_root=None, *, roles=None, campaign_root=None):
    """The scoring record of one question: every original passage beside its assessment.

    Without a graph (``graph_root`` None) or with a refused, failed or incomplete one, the
    originals are still returned; each affected candidate carries the error reason and no
    score. Only an unreadable or altered request pin raises, because it holds the originals.
    """
    document = _read_request(request_pin)
    outcomes, graph = _admit(document, request_pin, graph_root, roles, campaign_root)
    assessments = {}
    for skipped in document['not_scored']:
        assessments[skipped['id']] = {'status': 'not_scored', 'relevance_score': None, 'relevant': None,
                                      'summary': None, 'summary_origin': None, 'batch': None,
                                      'reason': skipped['reason'], 'error': None}
    for outcome in outcomes:
        for identity in outcome['candidates']:
            if outcome['status'] == 'admitted':
                score, summary = outcome['scores'][identity]
                assessments[identity] = {'status': 'scored', 'relevance_score': score, 'relevant': score > SCORE_MIN,
                                         'summary': summary, 'summary_origin': 'generated', 'batch': outcome['batch'],
                                         'reason': None, 'error': None}
            else:
                assessments[identity] = {'status': 'error', 'relevance_score': None, 'relevant': None,
                                         'summary': None, 'summary_origin': None, 'batch': outcome['batch'],
                                         'reason': outcome['reason'], 'error': deepcopy(outcome['error'])}
    rows = document['envelope']['results']
    evidence = [{'id': row['id'], 'rank': row['scores']['rank'], 'original': deepcopy(row),
                 'assessment': assessments[row['id']]} for row in rows]
    scored = [item for item in evidence if item['assessment']['status'] == 'scored']
    ranking = [item['id'] for item in sorted(scored, key=lambda i: (-i['assessment']['relevance_score'], i['rank']))]
    admitted = sum(o['status'] == 'admitted' for o in outcomes)
    status = ('nothing_to_score' if not outcomes else 'complete' if admitted == len(outcomes)
              else 'partial' if admitted else 'not_run' if all(o['reason'] == 'not_run' for o in outcomes)
              else 'failed')
    record = {'schema_version': 1, 'kind': KIND, 'question': document['question'], 'role': document['role'],
              'profile': document['profile'], 'limits': deepcopy(document['limits']),
              'request': {'path': str(Path(request_pin['path']).resolve()), 'sha256': request_pin['sha256']},
              'envelope_sha256': document['envelope_sha256'], 'provider_id': document['envelope']['provider_id'],
              'index': deepcopy(document['envelope']['index']),
              'search_request_id': document['envelope']['request_id'],
              'search_receipt_id': document['envelope']['receipt_id'], 'graph': graph, 'status': status,
              'evidence': evidence, 'ranking': ranking,
              'batches': [{k: v for k, v in o.items() if k != 'scores'} for o in outcomes],
              'usage': _usage(outcomes), 'summaries_are_evidence': False, 'physics_verified': False,
              'execution_authorized': False}
    record['sha256'] = _digest(literature_provider.canonical(record))
    return record


def write_record(path, record):
    """Write one scoring record to a fresh file and return its pin."""
    if type(record) is not dict or record.get('kind') != KIND or not _SHA.match(str(record.get('sha256'))):
        raise ValueError('evidence scoring record required')
    body = {k: v for k, v in record.items() if k != 'sha256'}
    if _digest(literature_provider.canonical(body)) != record['sha256']:
        raise ValueError('evidence scoring record digest differs')
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('ordinary record destination required')
    raw = _bytes(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path.resolve()), 'sha256': _digest(raw), 'size': len(raw)}


def _read_json(path):
    raw = Path(path).read_bytes()
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError(f'{path}: input exceeds {MAX_REQUEST_BYTES} bytes')
    return _loads(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Governed deep evidence scoring of served literature candidates. '
                                                 'This command makes no model call; the caller runs the Graph.')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='write the request and batch inputs, and optionally the Graph spec')
    prepare.add_argument('--question', required=True)
    prepare.add_argument('--search-request', required=True, help='the provider request JSON')
    prepare.add_argument('--envelope', required=True, help='the served retrieval envelope JSON')
    prepare.add_argument('--out', required=True, help='request path; batch files are written beside it')
    prepare.add_argument('--limits', help='JSON object overriding ' + ', '.join(sorted(LIMITS)))
    prepare.add_argument('--graph-spec-out')
    prepare.add_argument('--graph-id')
    prepare.add_argument('--model')
    prepare.add_argument('--reasoning-effort')
    prepare.add_argument('--adapter', default='model', choices=ADAPTERS)
    record = commands.add_parser('assemble', help='print the scoring record from the recorded Graph')
    record.add_argument('--request', required=True)
    record.add_argument('--request-sha256', required=True)
    record.add_argument('--graph-root')
    args = parser.parse_args(argv)
    try:
        if args.command == 'prepare':
            spec_args = (args.graph_id, args.model, args.reasoning_effort)
            if args.graph_spec_out and not all(spec_args):
                raise ValueError('--graph-spec-out requires --graph-id, --model and --reasoning-effort')
            document = request_document(args.question, _read_json(args.search_request), _read_json(args.envelope),
                                        limits=_loads(args.limits) if args.limits else None)
            pin = write_request(args.out, document)
            result = {'request': pin, 'batches': len(document['batches']), 'not_scored': document['not_scored']}
            if args.graph_spec_out:
                spec = graph_spec(pin, graph_id=args.graph_id, model=args.model, reasoning_effort=args.reasoning_effort,
                                  adapter=args.adapter)
                target = Path(args.graph_spec_out)
                with target.open('xb') as stream:
                    stream.write(_bytes(spec))
                result['graph_spec'] = str(target.resolve())
        else:
            result = assemble({'path': args.request, 'sha256': args.request_sha256}, args.graph_root)
    except (ValueError, OSError) as exc:
        print(f'literature_evidence_scoring: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
