"""Local P11 binding fakes with genuine inert provider parsing and child gates."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile

from ravel.workflow import candidate_experiments as ce, state_io
from ravel.workflow import graph_environment  # noqa: F401
from langgraph.checkpoint.memory import InMemorySaver

_UNIT = str(Path(__file__).resolve().parents[1])
if _UNIT not in sys.path:
    sys.path.insert(0, _UNIT)
from test_research_full_cycle_transport import InertReviewHost  # noqa: E402


def _json(value):
    return json.loads(json.dumps(value, allow_nan=False))


class FakeRunStore:
    def __init__(self, run_id, *, root=None):
        self.run_id = run_id
        self.store_root = Path(root or tempfile.mkdtemp(prefix='p11-store-')).resolve()
        self.root = self.store_root / run_id
        self.root.mkdir(parents=True, exist_ok=True)
        self.rows = []
        self._checkpointer = InMemorySaver()

    def append(self, kind, record):
        identity = str(len(self.rows) + 1)
        self.rows.append(_json({'id': identity, 'kind': kind, 'record': record}))
        return identity

    def read(self, kind, record_id):
        return deepcopy(next(row for row in self.rows if row['id'] == record_id and row['kind'] == kind))

    def scan(self, kind=None):
        return deepcopy([row for row in self.rows if kind is None or row['kind'] == kind])

    def path(self, *parts):
        result = self.root.joinpath(*parts)
        result.parent.mkdir(parents=True, exist_ok=True)
        return result

    def checkpointer(self):
        return self._checkpointer


class FakeControl:
    def __init__(self, context):
        self.root = Path(context['research']['graph_root']) if context.get('research', {}).get('graph_root') else None

    def call(self, label, kind, body, fn, output_tokens=0):
        return fn()

    def cancelled(self):
        return False


def _stage_response(node, context):
    fields = node['parameters']['output_schema']['properties']
    return {**{key: fields[key]['const'] for key in ('stage', 'role_id', 'subject_sha256')},
            'verdict': 'accept', 'findings': [], 'attributed_claim_ids': []}


class FakeStep:
    """The dispatcher chooses identities; public workers supply only public JSON."""
    def __init__(self, host=None, script=()):
        self.host = host if host is not None else InertReviewHost()
        self.script = list(script)
        self.calls = []
        self._attempts = {}
        # A governed step runs in a fresh context (``research_controller.governed_call``), so the host a scoped
        # dispatch delegates to is kept on the fake itself, never in an ambient ContextVar.
        self._delegates = []

    def run(self, store, step, context):
        identity = step['id']
        attempt = self._attempts.get(identity, 0) + 1
        self._attempts[identity] = attempt
        scripted = self.script.pop(0) if self.script else 'complete'
        status = scripted.get('status', 'complete') if isinstance(scripted, dict) else scripted
        if status not in {'held', 'failed', 'budget_exhausted', 'complete', 'completed'}:
            raise ValueError('unknown fake step script status')
        outcome = {'step_id': identity, 'attempt': attempt,
            'status': 'completed' if status in {'complete', 'completed'} else status,
            'outputs': [], 'receipts': [], 'escalation': None, 'replan': None,
            'budget': {}, 'judgments': [], 'review': {},
            'reason': scripted.get('reason') if isinstance(scripted, dict) else
                      (None if status in {'complete', 'completed'} else 'inert scripted ' + status)}
        call = _json({'step': step, 'context': context, 'attempt': attempt})
        self.calls.append(call)
        store.append('step', call)
        if outcome['status'] != 'completed':
            return outcome
        if step['kind'] == 'route':
            from ravel.workflow import science
            child = context['child_rundir']
            science.verify_plan(child, approved=True)
            code = science.run(child, resume=bool(step.get('parameters', {}).get('resume')))
            if code != 0:
                outcome.update(status='failed', reason='ordinary child exited ' + str(code))
            return outcome

        research = context['research']
        node, request = research['node'], research['request']
        fields = (node['parameters'].get('output_schema') or {}).get('properties', {})
        stage = {'stage', 'role_id', 'subject_sha256'} <= fields.keys()
        host = InertReviewHost(_stage_response) if stage else (self._delegates[-1] if self._delegates else self.host)
        result = host.execute(deepcopy(node), deepcopy(request), FakeControl(context))
        public = result['value'] if result.get('kind') == 'model_result' else result
        public = _json(public)
        target = (Path(context['run_dir']) / 'steps' / identity / 'outputs' / 'public-record.json').resolve()
        state_io.atomic_json(target, public)
        outcome['outputs'] = [{'path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}]
        transport = deepcopy(result.get('transport') or {}) if node['kind'] == 'model' else {}
        observed = {'step_id': identity, 'attempt': attempt, 'node_id': node['id'],
            'status': 'ok', 'actor_id': 'p11-dispatcher-' + identity,
            'session_id': transport.get('response_id') or request['request_id'],
            'model': {'requested': transport.get('requested_model'), 'observed': transport.get('observed_model')},
            'usage': deepcopy(result.get('usage') or {}) if node['kind'] == 'model' else {},
            'transport_evidence': transport,
            'isolation': deepcopy(result.get('isolation') or {}) if node['kind'] == 'model' else {}}
        receipt = ce.digest(observed)
        observed['receipt_sha256'] = receipt
        store.append('step-observation', observed)
        outcome['receipts'] = [receipt]
        return outcome


@contextmanager
def installed_step(fake):
    import pytest
    from ravel.controller import step
    from ravel.workflow import research_controller as bridge
    original = bridge.governed_host

    def governed(delegate):
        active = bridge.active()
        if active is None:
            return original(delegate)

        class ScopedHost(bridge.GovernedHost):
            def execute(self, node, request, control):
                fake._delegates.append(delegate if isinstance(delegate, InertReviewHost) else fake.host)
                try:
                    return super().execute(node, request, control)
                finally:
                    fake._delegates.pop()
        return ScopedHost(*active)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(bridge, 'governed_host', governed)
        patch.setattr(step, 'run', fake.run)
        yield fake


@contextmanager
def captured_operator(tmp_path):
    """The explicit inert operator stand-in over the real capture chain and verifier.

    ``operator_capture.confirm`` calls the unchanged ``approval_capture._record``; terminal I/O
    is never used. The shared conftest fixture keeps the capture ledger private for the whole
    test. The copied authority fixture class takes the confirmed ``Run.approve`` for the block
    and has its original method restored on exit.
    """
    import pytest
    import operator_capture
    import rdj_fixtures
    from test_research_full_cycle_authority import Authority
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Authority, 'approve', rdj_fixtures.Run.approve)
        yield operator_capture
