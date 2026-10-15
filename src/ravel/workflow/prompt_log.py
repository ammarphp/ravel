"""Export exact prompt evidence, conservative model identities and supplied-price totals.

Unknown or changed evidence remains a row with gaps. Reading a request never
executes it. The source census is a syntactic control, not runtime attestation.
"""
import argparse
from collections import defaultdict
from functools import lru_cache
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from math import fsum, isfinite
from pathlib import Path
import re
import sys
from uuid import uuid4

from . import agent_audit as aa

MAX_PROMPT_BYTES = 16 * 1024 * 1024
MAX_DOCUMENT_BYTES = 256 * 1024
NOT_DELIVERED = {'instruction_document_sha256': None, 'instruction_delivery': None}
_PROCESS_SESSION = uuid4().hex


def session_recording_destination():
    """A stable session folder, including for hosts without a session identifier."""
    from .active_run import state_dir, session_from_env
    session = session_from_env() or _PROCESS_SESSION
    return state_dir() / 'prompt-log' / _hash(session), session


def exact_model(model):
    """Only a reported calendar snapshot establishes an exact build here."""
    if not isinstance(model, str):
        return False
    match = re.search(r'(?<!\d)(20\d{2})-?(\d{2})-?(\d{2})(?!\d)', model)
    if not match:
        return False
    try:
        datetime(*map(int, match.groups()))
    except ValueError:
        return False
    return True


def _read(root, path):
    from .worker_audit import _inside
    path = _inside(root, path)
    if path.stat().st_size > MAX_PROMPT_BYTES:
        raise ValueError('prompt evidence exceeds byte bound')
    return json.loads(path.read_bytes())


def _hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def delivery_record(receipt):
    """The project-instruction delivery record a receipt carries, or None.

    A worker receipt keeps it in ``transport.project_instructions``; a one-shot session
    receipt keeps it in ``configuration.project_instructions``. No other field is read.
    """
    if not isinstance(receipt, dict):
        return None
    section = receipt.get('transport') if receipt.get('kind') == 'agent-worker-receipt' else receipt.get('configuration')
    return section.get('project_instructions') if isinstance(section, dict) else None


def delivery_fields(receipt):
    """``(row fields, flags)`` from the receipt's delivery record: the document sha256 and the mechanism."""
    record = delivery_record(receipt)
    if record is None or record == {'status': 'not_started'}:
        return dict(NOT_DELIVERED), []
    sha = record.get('sha256') if isinstance(record, dict) else None
    if (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha)
            or not isinstance(record.get('mechanism'), str)):
        return dict(NOT_DELIVERED), ['instruction delivery record malformed']
    return {'instruction_document_sha256': sha, 'instruction_delivery': record['mechanism']}, []


def _document_text(record, root=None):
    """The declared document's text, checked against the recorded sha256, else None.

    The file the record names is read while it still holds the recorded bytes. After a re-pin
    or an edit it does not; the run's custody folder keeps the bytes of every document the
    run pinned, named by their sha256, and that copy is read instead.
    """
    try:
        candidates = [Path(record['path'])]
        if root is not None and isinstance(record['sha256'], str) and re.fullmatch(r'[0-9a-f]{64}', record['sha256']):
            from .worker_audit import _custody_file, _custody_folder
            try:
                candidates.append(_custody_file(root, _custody_folder(root) / f'project-instructions.{record["sha256"]}.md'))
            except ValueError:
                pass
        for path in candidates:
            if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_DOCUMENT_BYTES:
                continue
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() == record['sha256']:
                return raw.decode('utf-8')
        return None
    except (OSError, KeyError, TypeError, UnicodeError):
        return None


def _kept_prompt(root, path, prompt_sha256):
    """``(text, source, flags)``: the exact prompt a launcher or host kept beside a receipt file.

    The file is ``<receipt file without .json>.prompt.txt``. It is the prompt only when it is a
    regular file inside the run and hashes to the receipt's prompt digest.
    """
    kept = Path(path).with_suffix('.prompt.txt')
    if not kept.exists() and not kept.is_symlink():
        return None, None, []
    try:
        from .worker_audit import _inside
        kept = _inside(root, kept)
        if not kept.is_file() or kept.stat().st_size > MAX_PROMPT_BYTES:
            raise ValueError('kept prompt is not a bounded regular file')
        text = kept.read_bytes().decode('utf-8')
    except (OSError, ValueError, UnicodeError):
        return None, None, ['kept prompt file refused']
    if not isinstance(prompt_sha256, str) or _hash(text) != prompt_sha256:
        return None, None, ['kept prompt differs from the receipt prompt digest']
    return text, aa.pin(kept), []


def _first_block(text, record):
    """The block a session received ahead of the request when its document travelled in the prompt, else None."""
    try:
        from . import project_instructions
        return project_instructions.block(text, record)
    except (ImportError, AttributeError, KeyError, TypeError):
        return None


def _row(record):
    model = record.get('model_reported', record.get('model'))
    mixed = len(record.get('models') or []) > 1
    if mixed:
        model = None
    usage = record.get('usage') or {}
    row = {**record, 'model_requested': record.get('model_requested'), 'model_reported': model,
           'model_build_exact': exact_model(model), 'cli_version': record.get('cli_version'),
           'role': record.get('role') or record.get('ravel', {}).get('role_id'),
           'instruction_document_sha256': record.get('instruction_document_sha256'),
           'instruction_delivery': record.get('instruction_delivery'),
           'system_prompt_append': record.get('system_prompt_append'),
           'flags': list(record.get('flags', []))}
    if mixed:
        row['flags'].append('multiple models; per-model usage attribution unknown')
    row['total_tokens'] = usage.get('total_tokens')
    row['prompt_sha256'] = record.get('prompt_sha256') or (_hash(row['prompt']) if isinstance(row.get('prompt'), str) else None)
    if not row['model_build_exact']:
        row['flags'].append('model build inexact')
    if not isinstance(row.get('prompt'), str):
        row['flags'].append('full prompt unknown')
    elif len(row['prompt'].encode()) > MAX_PROMPT_BYTES or _hash(row['prompt']) != row['prompt_sha256']:
        row['prompt'] = None
        row['flags'].append('prompt hash or size differs')
    try:
        if datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00')).tzinfo is None:
            raise ValueError()
    except (KeyError, ValueError, TypeError, AttributeError):
        row['flags'].append('timezone-aware timestamp unknown')
    if (any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('input_tokens', 'output_tokens', 'total_tokens'))
            or usage['total_tokens'] != usage['input_tokens'] + usage['output_tokens']):
        row['usage'] = {k: None for k in aa.USAGE_KEYS}
        row['total_tokens'] = None
        row['flags'].append('token accounting unknown or inconsistent')
    elif any(type(usage.get(k, 0)) is not int or usage.get(k, 0) < 0 for k in ('cached_input_tokens', 'cache_creation_input_tokens')) or sum(usage.get(k) or 0 for k in ('cached_input_tokens', 'cache_creation_input_tokens')) > usage['input_tokens']:
        row['flags'].append('cache token accounting inconsistent')
    row['flags'] = sorted(set(row['flags']))
    return row


def _launcher(root, path, receipt, requests):
    reported = receipt.get('cli_reported', {})
    content = receipt.get('content', {})
    # Only a recorded request digest binds a request; two absent digests are not a match.
    digest = content.get('request_sha256')
    matched = [r for r in requests if isinstance(digest, str) and r[1].get('sha256') == digest]
    # A successful session keeps its exact prompt beside the receipt file; that text needs no rebuilding.
    kept, kept_source, kept_flags = _kept_prompt(root, path, content.get('prompt_sha256'))
    prompt = kept or receipt.get('prompt_text') or content.get('prompt_text')
    parameters, context, request = {}, {}, {}
    rendered_by = None
    delivered, flags = delivery_fields(receipt)
    flags.extend(kept_flags)
    # A declared document reached the session in the prompt's first block, or behind a flag
    # outside the prompt. Its text is the recorded file or the custody copy, checked against the record.
    first_block, appended = '', None
    if delivered['instruction_document_sha256'] is not None:
        record = delivery_record(receipt)
        text = _document_text(record, root)
        if delivered['instruction_delivery'] != 'prompt_first_block':
            # Behind a flag the prompt itself holds no document text.
            if text is None:
                flags.append('declared document bytes unavailable')
            appended = text
        elif kept is None:
            # A kept prompt already holds the first block; only a rebuilt one needs the document.
            if text is None:
                flags.append('declared document bytes unavailable')
                first_block = None
            else:
                first_block = _first_block(text, record)
                if first_block is None:
                    flags.append('declared document block renderer unavailable')
    for request_path, document in matched:
        parameters, context, request = document.get('parameters', {}), document.get('context', {}), document.get('request', {})
        if prompt is None and first_block is not None:
            from . import cli_agent_host
            try:
                candidate = first_block + cli_agent_host.build_prompt(parameters, context)
                if _hash(candidate) == content.get('prompt_sha256'):
                    prompt = candidate
                    rendered_by = aa.pin(cli_agent_host.__file__)
            except (KeyError, TypeError, ValueError):
                continue
        if prompt is not None:
            break
    process = receipt.get('process', {})
    elapsed = process.get('elapsed_seconds')
    if elapsed is None and process.get('finished_utc') and process.get('started_utc'):
        try:
            elapsed = (datetime.fromisoformat(process['finished_utc'].replace('Z', '+00:00')) -
                       datetime.fromisoformat(process['started_utc'].replace('Z', '+00:00'))).total_seconds()
        except ValueError:
            pass
    return _row({'prompt': prompt, 'prompt_sha256': content.get('prompt_sha256'),
        'timestamp': process.get('started_utc'), 'usage': reported.get('usage'),
        'model_requested': parameters.get('model'), 'model_reported': reported.get('observed_model'),
        'cli_version': receipt.get('executable', {}).get('cli_version'),
        'session_id': reported.get('session_id') or receipt.get('invocation', {}).get('host_invocation_id'),
        'invocation_id': receipt.get('invocation', {}).get('host_invocation_id'),
        'role': context.get('role'), 'node_id': request.get('node_id'), 'source': aa.pin(path),
        **delivered, 'system_prompt_append': appended, 'flags': flags,
        'request_source': aa.pin(request_path) if matched else None, 'renderer_source': rendered_by,
        'prompt_source': kept_source,
        'elapsed_seconds': elapsed, 'stream': 'oneshot', 'prompt_index': 1})


def _graph_role(root, path, node_id):
    spec = path.parent.parent / 'graph_spec.json'
    if spec.exists():
        return next((n.get('role') for n in _read(root, spec).get('nodes', []) if n.get('id') == node_id), None)
    return None


def _loop_record(root, path, document):
    """Collect one model effect, including unfinished turns with unknown usage."""
    from .effect_ledger import digest
    identity = document.get('identity') or {}
    result = document.get('result') or {}
    flags = []
    prompt = result.get('prompt')
    if prompt is None:
        # A turn without a result (its sender failed after dispatch) still has the request the loop
        # kept with the effect before sending. The effect's request digest binds it below.
        prompt = (document.get('provisioning') or {}).get('wire_request')
    if digest({**identity, 'kind': document['kind']}) != document.get('identity_sha256'):
        flags.append('loop request identity hash differs')
        prompt = None
    if result and digest(result) != document.get('result_sha256'):
        flags.append('loop result hash differs')
        result, prompt = {}, None
    if prompt is not None:
        try:
            if digest(json.loads(prompt)) != identity.get('wire_request_sha256'):
                raise ValueError('wire request differs')
        except (ValueError, TypeError):
            flags.append('loop wire request hash differs')
            prompt = None
    usage = dict(result.get('usage') or {})
    if all(type(usage.get(k)) is int for k in ('input_tokens', 'output_tokens')):
        usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
    turn = re.search(r'/turn:(\d+)/model$', document.get('path', ''))
    return _row({'prompt': prompt, 'prompt_sha256': result.get('prompt_sha256') or (
            identity.get('wire_request_sha256') if prompt is not None else None),
        'timestamp': document.get('started_utc'), 'usage': usage,
        'model_requested': result.get('model_requested'), 'model_reported': result.get('model_reported'),
        'session_id': identity.get('loop_binding'), 'call_id': document['call_id'],
        'node_id': document.get('node_id'), 'role': _graph_role(root, path, document.get('node_id')),
        'status': document.get('status'), 'source': aa.pin(path), 'flags': flags,
        'elapsed_seconds': document.get('elapsed_seconds'), 'stream': 'loop',
        'prompt_index': int(turn.group(1)) + 1 if turn else 1})


# The collector and census use the same routes. Removing a collector removes its
# spending-site mapping; recognizing a sender alone never establishes coverage.
EFFECT_COLLECTORS = {'ravel-loop': _loop_record}


def receipt_records(root):
    """Collect standalone launchers, host wrappers, provider receipts and graph calls."""
    root = Path(root).absolute()
    rows, gaps, requests = [], [], []
    for path in sorted(root.glob('**/requests/*.json')):
        try:
            document = _read(root, path)
            if not isinstance(document, dict):
                raise ValueError('request is not a JSON object')
            requests.append((path, document))
        except (OSError, ValueError, TypeError) as exc:
            gaps.append({'path': str(path), 'reason': str(exc)})
    # Standalone answer accepts a caller-supplied request filename. Discover its
    # document kind rather than assuming a layout. Unrelated JSON is not evidence.
    requested_paths = {str(p) for p, _ in requests}
    for path in sorted(root.glob('**/*.json')):
        if str(path) in requested_paths:
            continue
        try:
            document = _read(root, path)
            if isinstance(document, dict) and document.get('kind') == 'external_agent_request':
                requests.append((path, document))
        except (OSError, ValueError, TypeError):
            continue
    patterns = ('**/*.receipt.json', '**/transport-receipts/*.json', '**/prompt-receipts/*.json', '**/calls/*.json')
    paths = sorted({p for pattern in patterns for p in root.glob(pattern)})
    for path in paths:
        try:
            document = _read(root, path)
            if not isinstance(document, dict):
                raise ValueError('receipt is not a JSON object')
            if document.get('kind') == 'model-prompt-receipt':
                rows.append(_row({**document, 'source': aa.pin(path)}))
                continue
            receipt = document.get('launcher_receipt')
            if receipt is None and 'cli_reported' in document:
                receipt = document
            if receipt is not None:
                rows.append(_launcher(root, path, receipt, requests))
                continue
            if document.get('kind') != 'model':
                continue
            collector = EFFECT_COLLECTORS.get((document.get('graph') or {}).get('id'))
            if callable(collector):
                rows.append(collector(root, path, document))
                continue
            result = document.get('result') or {}
            transport = result.get('transport') or {}
            receipt = (transport.get('session_receipt') or {}).get('launcher_receipt')
            if receipt:
                rows.append(_launcher(root, path, receipt, requests))
            # Framework effect records duplicate graph calls. Only the graph call
            # journal is a fallback census; durable prompt receipts take priority.
            elif 'call_id' in document and 'graph' not in document:
                rows.append(_row({'prompt': None, 'timestamp': document.get('started_utc'),
                    'usage': result.get('usage'), 'model_requested': transport.get('requested_model'),
                    'model_reported': transport.get('observed_model'), 'session_id': transport.get('response_id'),
                    'node_id': document.get('node_id'), 'call_id': document['call_id'],
                    'role': _graph_role(root, path, document.get('node_id')), 'status': document.get('status'),
                    'source': aa.pin(path), 'elapsed_seconds': document.get('elapsed_seconds'),
                    'stream': 'graph', 'prompt_index': 1}))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            gaps.append({'path': str(path), 'reason': str(exc)})
    # Prefer complete rows when launcher receipts are nested in other receipts.
    rows.sort(key=lambda r: (len(r['flags']), r['source']['path']))
    unique, calls = {}, set()
    for row in rows:
        if row.get('call_id') and row['stream'] != 'graph':
            calls.add(row['call_id'])
        key = row.get('invocation_id') or row.get('call_id') or row.get('session_id') or row['source']['path']
        unique.setdefault(key, row)
    rows = [r for r in unique.values() if r['stream'] != 'graph' or r.get('call_id') not in calls]
    return rows, gaps


def call_site_census(source_root=None):
    from ravel.validation.check_agent_paths import SRC
    root = Path(source_root) if source_root is not None else SRC
    fingerprint = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(root.rglob('*.py')))
    routes = tuple(sorted(k for k, v in EFFECT_COLLECTORS.items() if callable(v)))
    return deepcopy(_call_site_census(str(root), fingerprint, routes))


@lru_cache(maxsize=2)
def _call_site_census(source_root, fingerprint, effect_routes):
    """Extend the repository AST census with actual host dispatch and CLI sinks.

    Mappings describe collected record paths, never silently sanction a new
    caller. Unknown SDKs, agent loops and new dispatch sites remain gaps.
    """
    from ravel.validation import check_agent_paths as checks
    import ast
    root = Path(source_root) if source_root is not None else checks.SRC
    rows = []
    non_spending = []
    records = {
        'ravel.workflow.cli_agent_host:serve': '**/transport-receipts/*.json',
        'ravel.workflow.cli_agent_host:answer': '**/*.receipt.json + **/requests/*.json',
        'ravel.workflow.cli_agent_host:answer_graph.answer_one': '**/external-responses/*.receipt.json',
        'ravel.workflow.cli_agent_host:main': 'delegates to serve, answer or answer_graph',
        'ravel.workflow.cli_agent_host:invoke': 'returned launcher receipt; persisted by caller',
        'ravel.workflow.cli_agent_host:_run': 'returned launcher receipt; persisted by caller',
        'ravel.workflow.agent_host:AgentHost.execute': '**/prompt-receipts/*.json + **/calls/*.json',
        'ravel.workflow.agent_host:AgentHost._responses': '**/prompt-receipts/*.json',
        'ravel.workflow.agent_host:AgentHost._command_process': '**/calls/*.json + **/transport-receipts/*.json',
        'ravel.workflow.agent_worker:supervise': '**/agent-work/*/*/receipt.json + transcript.jsonl',
        'ravel.workflow.transports.cli_worker:run': '**/agent-work/*/*/receipt.json + transcript.jsonl',
        # A caller-supplied dispatcher runs inside provider_transport.recorded_dispatch, which keeps the
        # request handed over before the call and the outcome after it.
        'ravel.workflow.agentrivet_provider:GraphLLM._generate': '**/prompt-receipts/*.json (stream=dispatcher) + **/requests/*.json',
    }
    if 'ravel-loop' in effect_routes:
        records.update({
            'ravel.workflow.ravel_chat_model:RavelTransportChatModel.turn.dispatch': '**/calls/*.json (model effects, graph.id=ravel-loop)',
            'ravel.transports.ravel_loop:RavelLoop._model': '**/calls/*.json (model effects, graph.id=ravel-loop)',
        })
    for path in sorted(root.rglob('*.py')):
        relative = path.relative_to(root.parent).as_posix()
        module, package = checks._module_name(Path(relative))
        text = path.read_text()
        found = checks.scan_source(text, module=module, path=relative, is_package=package)
        classified = checks.classify(found, checks.load_sanctioned())
        non_model = {r['qualname'] for r in classified if r['disposition'] == 'non_model'}
        for row in classified:
            if row['sink'] in ('S1', 'S4') and row['disposition'] != 'non_model':
                rows.append(row)
            elif row['sink'] == 'S5':
                # These are constructor/static-prompt references in the source
                # checker. Keep them separate from actual generation dispatch.
                non_spending.append({**row, 'basis': 'upstream reference; actual dispatch is inventoried separately'})
        # Dynamic argv and a connection's bound request method have no static
        # receiver in the general census. Include them at function granularity.
        class Dispatch(ast.NodeVisitor):
            def __init__(self):
                self.stack = []
            def visit_FunctionDef(self, node):
                self.stack.append(node.name); self.generic_visit(node); self.stack.pop()
            visit_AsyncFunctionDef = visit_FunctionDef
            def visit_ClassDef(self, node):
                self.stack.append(node.name); self.generic_visit(node); self.stack.pop()
            def visit_Call(self, node):
                name = ast.unparse(node.func)
                if name in ('control.call', 'connection.request', '_run', 'subprocess.Popen', 'self.dispatcher', 'self.sender', 'self.model.turn'):
                    qualname = module + ':' + '.'.join(self.stack)
                    if name == '_run' and module != 'ravel.workflow.cli_agent_host':
                        return
                    if name == 'connection.request' and qualname in non_model:
                        return
                    # Other process launches are deterministic tools. A model
                    # transport's low-level launch is included regardless of argv.
                    if name != 'subprocess.Popen' or qualname in records:
                        if qualname == 'ravel.workflow.agent_graph:prepare_external':
                            return  # Preparing an external request reserves tokens but sends no prompt.
                        if name != 'control.call' or any(isinstance(a, ast.Constant) and a.value == 'model' for a in node.args):
                            rows.append({'path': relative, 'line': node.lineno, 'qualname': qualname,
                                         'target': name, 'sink': 'dispatch'})
                self.generic_visit(node)
        Dispatch().visit(ast.parse(text))
    for row in rows:
        row['record'] = records.get(row['qualname'])
    unique = {(r['path'], r['line'], r['target']): r for r in rows}
    rows = sorted(unique.values(), key=lambda r: (r['path'], r['line'], r['target']))
    gaps = [{'path': r['path'], 'line': r['line'], 'reason': 'model call has no collected record mapping'}
            for r in rows if r['record'] is None]
    return {'rows': rows, 'gaps': gaps, 'complete': not gaps, 'files_scanned': len(list(root.rglob('*.py'))),
            'non_spending_references': non_spending,
            'scope': 'Static source inventory; dynamic external implementations require runtime qualification.'}


def _totals(rows, price_table):
    if price_table is not None and not isinstance(price_table, dict):
        raise ValueError('price table must be an object keyed by reported model')
    groups = {name: defaultdict(list) for name in ('model', 'role')}
    for row in rows:
        groups['model'][row['model_reported'] or 'unknown'].append(row)
        groups['role'][row['role'] or 'unknown'].append(row)
    def sum_rows(selected):
        result = {key: fsum(r.get('usage', {}).get(key) or 0 for r in selected) for key in aa.USAGE_KEYS}
        result['unknown_token_rows'] = sum(r['total_tokens'] is None for r in selected)
        result['wall_seconds'] = fsum(r['elapsed_seconds'] for r in selected if isinstance(r.get('elapsed_seconds'), (int, float)) and isfinite(r['elapsed_seconds']) and r['elapsed_seconds'] >= 0)
        result['unknown_wall_rows'] = sum(r.get('elapsed_seconds') is None for r in selected)
        return result
    totals = sum_rows(rows)
    totals['by_model'] = {k: sum_rows(v) for k, v in sorted(groups['model'].items())}
    totals['by_role'] = {k: sum_rows(v) for k, v in sorted(groups['role'].items())}
    if price_table is not None:
        for model, rates in price_table.items():
            if not isinstance(rates, dict) or any(type(rates.get(k)) not in (int, float) or not isfinite(rates[k]) or rates[k] < 0 for k in ('input_per_million', 'output_per_million', *[k for k in ('cached_input_per_million', 'cache_creation_input_per_million') if k in rates])):
                raise ValueError('price table requires finite nonnegative input_per_million and output_per_million rates')
        costs, unknown = [], 0
        for row in rows:
            rates = price_table.get(row['model_reported'])
            if rates is None or row['total_tokens'] is None or 'cache token accounting inconsistent' in row['flags']:
                unknown += 1; continue
            usage = row['usage']
            # Cache rates, when supplied, replace input pricing for those tokens.
            cached = usage.get('cached_input_tokens') or 0
            created = usage.get('cache_creation_input_tokens') or 0
            costs.append(fsum(((usage['input_tokens'] - cached - created) * rates['input_per_million'],
                cached * rates.get('cached_input_per_million', rates['input_per_million']),
                created * rates.get('cache_creation_input_per_million', rates['input_per_million']),
                usage['output_tokens'] * rates['output_per_million'])) / 1e6)
        totals.update(cost_estimate=fsum(costs), unpriced_rows=unknown)
    return totals


def build(rundir, transcripts=(), *, price_table=None):
    from . import worker_audit
    audit = worker_audit.build(rundir)
    rows = [_row(r) for r in audit.get('records', [])]
    gaps = list(audit['gaps'])
    known = {(r.get('session_id'), r.get('stream'), r.get('prompt_index')) for r in rows}
    for path in dict.fromkeys(map(str, transcripts)):
        try:
            parsed = aa.parse(path)
            for record in parsed['records']:
                key = record.get('session_id'), record.get('stream'), record.get('prompt_index')
                if key not in known:
                    rows.append(_row(record)); known.add(key)
        except (OSError, ValueError, TypeError) as exc:
            gaps.append({'path': str(path), 'reason': str(exc)})
    # Hook-produced copies remain usable after the original transcript is gone.
    root = Path(rundir).absolute()
    for hook in sorted(root.glob('**/.ravel/agent-audit/prompts.jsonl')):
        try:
            from .worker_audit import _inside
            source = aa.pin(_inside(root, hook))
            events = aa.read_log(hook)
            for event in events:
                if event.get('event') == 'turn_recorded':
                    record = event['record']
                    key = record.get('session_id'), record.get('stream'), record.get('prompt_index')
                    if key not in known:
                        rows.append(_row(record)); known.add(key)
            texts = {(r.get('session_id'), r.get('prompt')) for r in rows}
            for event in events:
                if event.get('event') == 'prompt_submitted' and (event.get('session_id'), event.get('prompt')) not in texts:
                    rows.append(_row({'prompt': event.get('prompt'), 'timestamp': event.get('timestamp'),
                        'session_id': event.get('session_id'), 'source': source, 'stream': 'hook',
                        'prompt_index': len(rows) + 1, 'role': 'interactive'}))
                    texts.add((event.get('session_id'), event.get('prompt')))
                elif event.get('event') == 'codex_turn_complete':
                    prompts = event.get('input_messages', [])
                    for index, prompt in enumerate(prompts):
                        if isinstance(prompt, str) and (event.get('thread_id'), prompt) not in texts:
                            rows.append(_row({'prompt': prompt, 'timestamp': event.get('timestamp'),
                                'session_id': event.get('thread_id'), 'source': source, 'stream': 'notify',
                                'prompt_index': index + 1, 'role': 'interactive',
                                'flags': ['notification completion time; prompt submission time unknown']}))
                            texts.add((event.get('thread_id'), prompt))
        except (OSError, ValueError, TypeError, KeyError) as exc:
            gaps.append({'path': str(hook), 'reason': str(exc)})
    rows.sort(key=lambda r: (r.get('timestamp') or '', r.get('session_id') or '', str(r.get('prompt_index', 1))))
    for row in rows:
        gaps.extend({'source': row.get('source'), 'reason': flag} for flag in row['flags'])
    # The worker census already reports receipt-row flags; keep each gap once.
    gaps = list({json.dumps(g, sort_keys=True, default=str): g for g in gaps}.values())
    census = call_site_census()
    gaps.extend(census['gaps'])
    # The worker census names what no recorded session can show; the log carries that row once.
    if worker_audit.COVERAGE_LIMIT not in gaps:
        gaps.append(dict(worker_audit.COVERAGE_LIMIT))
    return {'schema_version': 1, 'rows': rows, 'totals': _totals(rows, price_table), 'gaps': gaps,
            'call_site_census': census, 'complete': not gaps}


def write(log, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl, markdown = out / 'prompt-log.jsonl', out / 'prompt-log.md'
    if jsonl.exists() or markdown.exists():
        raise FileExistsError('prompt log output already exists')
    lines = ['# Prompt log', '', '| Group | Input tokens | Output tokens | Total tokens | Wall seconds | Unknown token rows |',
             '|---|---:|---:|---:|---:|---:|']
    def cell(value):
        return str(value).replace('|', '&#124;').replace('\n', ' ')
    for kind in ('model', 'role'):
        for name, total in log['totals']['by_' + kind].items():
            lines.append(f"| {kind}: {cell(name)} | {total['input_tokens']} | {total['output_tokens']} | {total['total_tokens']} | {total['wall_seconds']} | {total['unknown_token_rows']} |")
    total = log['totals']
    lines.append(f"| All prompts | {total['input_tokens']} | {total['output_tokens']} | {total['total_tokens']} | {total['wall_seconds']} | {total['unknown_token_rows']} |")
    if 'cost_estimate' in total:
        lines += ['', '| Supplied-price cost estimate | Unpriced rows |', '|---:|---:|',
                  f"| {total['cost_estimate']} | {total['unpriced_rows']} |"]
    lines += ['', 'Totals: ' + json.dumps(log['totals'], sort_keys=True), '', '## Prompts', '']
    for index, row in enumerate(log['rows'], 1):
        lines += [f'### {index}', '', 'Metadata: ' + json.dumps({k: v for k, v in row.items() if k != 'prompt'}, ensure_ascii=False, sort_keys=True), '']
        prompt = row.get('prompt')
        if prompt is not None:
            fence = '`' * max(3, 1 + max((len(m.group()) for m in re.finditer(r'`+', prompt)), default=0))
            lines += [fence + 'text', prompt, fence, '']
        else:
            lines += ['Full prompt unavailable; see gaps.', '']
    lines += ['## Gaps', '', json.dumps(log['gaps'], indent=2, sort_keys=True), '', '## Call-site census', '',
              json.dumps(log['call_site_census'], indent=2, sort_keys=True), '']
    with jsonl.open('x', encoding='utf-8') as stream:
        stream.write(''.join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n' for r in log['rows']))
    with markdown.open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines))
    return {'jsonl': str(jsonl), 'markdown': str(markdown), 'prompts': len(log['rows']), 'gaps': len(log['gaps'])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rundir', type=Path, required=True)
    parser.add_argument('--transcripts', type=Path, nargs='*', default=[])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--price-table', type=Path)
    args = parser.parse_args(argv)
    try:
        prices = json.loads(args.price_table.read_text()) if args.price_table else None
        print(json.dumps(write(build(args.rundir, args.transcripts, price_table=prices), args.out), sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(f'prompt-log: {exc}', file=sys.stderr)
        return 2
