"""Review packet handling for authenticated computation outcomes."""
from copy import deepcopy
import ast
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ravel.workflow import broker, review_projection, review_projection_checks as rpc, role_registry
from test_p13_peer_projection import projection_path, setup_run  # noqa: F401
from test_p13_peer_wiring import step_seats  # noqa: F401
from test_p13_ml_stage_wiring import wired_graph  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
APPLY_FRAGMENT = True
PATCH_TEXT = r'''--- a/src/ravel/controller/step/graph.py
+++ b/src/ravel/controller/step/graph.py
@@ -595,10 +595,65 @@
     pinned = (state.get('card') or {}).get('registry_sha256')
     card, _, _ = cards.resolve(parent['role'], {'registry_sha256': pinned})
     return card
+
+
+def _ml_observations(state):
+    """Project every authenticated ML check for the bound specification, including failures."""
+    from ravel.workflow import broker, review_projection_checks as rpc
+    acting = state.get('acting') or {}
+    parent = state.get('step') or {}
+    store = _store(state)
+    role = (acting.get('role') or {}).get('id') if type(acting.get('role')) is dict else acting.get('role')
+    bindings = {}
+    for source in (acting.get('check_inputs') or {}, parent.get('check_inputs') or {}):
+        if type(source) is dict:
+            for check_id, binding in source.items():
+                if check_id in rpc.ML_RESULT_CHECKS:
+                    bindings.setdefault(check_id, binding)
+    spec_digests = {row.get('spec_sha256') for row in bindings.values() if type(row) is dict
+                    and type(row.get('spec_sha256')) is str}
+    references = {}
+    for check_id, binding in bindings.items():
+        record_id = binding.get('record_id') if type(binding) is dict else None
+        references[record_id if type(record_id) is str else 'missing:' + check_id] = (check_id, binding)
+    for envelope in store.scan(rpc.ML_OBSERVATION_KIND):
+        if type(envelope) is not dict:
+            continue
+        if type(envelope.get('record')) is dict:
+            row = envelope['record']
+            record_id = envelope.get('id')
+        else:
+            row = envelope
+            record_id = row.get('_record_id') or row.get('id') or row.get('record_id')
+        if row.get('spec_sha256') not in spec_digests or type(record_id) is not str or not record_id:
+            continue
+        binding = {'record_id': record_id, 'spec_sha256': row.get('spec_sha256'),
+                   'subject_sha256': row.get('subject_sha256')}
+        references.setdefault(record_id, (row.get('check_id'), binding))
+    observations = []
+    seen = set()
+    for record_id, (check_id, binding) in references.items():
+        if type(check_id) is not str or check_id not in rpc.ML_RESULT_CHECKS:
+            continue
+        if type(record_id) is str and record_id in seen:
+            continue
+        value = rpc.observed_ml_result(store, binding, check_id=check_id)
+        resolved_id = (binding or {}).get('record_id') if type(binding) is dict else None
+        if type(resolved_id) is str:
+            seen.add(resolved_id)
+        observations.append({'check_id': value['check_id'], 'status': value['status'],
+                             'diagnostics': deepcopy(value.get('diagnostics') or {}),
+                             'result_sha256': broker.digest(value), 'binding': deepcopy(binding)})
+    if not observations and role == 'ml-reviewer':
+        observations.append({'check_id': None, 'status': 'inconclusive',
+                             'diagnostics': {'reason': 'no bound ML computation observations'},
+                             'result_sha256': None, 'binding': None})
+    return observations
 
 
 def _worker_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations):
     from ravel.workflow import agent_worker, transport_registry as tr
+    ml_observations = _ml_observations(state)
     from ravel.workflow.transports import cli_worker
     seat = _seat(state)
     attempt = _attempt(state)
@@ -663,7 +718,8 @@
                                 'packet_sha256': packet_info['sha256'], 'budgets': applied,
                                 'toolbelt_manifest_sha256': belt['manifest_sha256'], 'admitted_tools': admitted['tools']})
     return {'spec': worker, 'spec_sha256': digest(worker), 'selection': selection, 'outputs': outputs,
-            'applied': applied, 'consults_pending': pending, 'dispatch_key': key, 'toolbelt': admitted}
+            'applied': applied, 'consults_pending': pending, 'dispatch_key': key, 'toolbelt': admitted,
+            'ml_observations': ml_observations}
 
 
 def _launch_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations):
@@ -774,8 +830,11 @@
             owed = instructions.reviewer_items(manifest, reviewer)
         except (KeyError, ValueError):
             owed = []
+        projection_state = dict(state)
+        projection_state['acting'] = {**(state.get('acting') or {}), 'role': role}
         items.append({'key': f'seat:{role}:1', 'purpose': 'review', 'role': role, 'n': 1,
                       'subject': _subject(adopted), 'items': deepcopy(owed),
+                      'findings': _ml_observations(projection_state),
                       'producer': {'session_id': (state.get('observation') or {}).get('session_id'),
                                    'role': card['id']}})
     return items
@@ -1045,8 +1104,12 @@
             if r.get('session_id') and r.get('receipt_sha256') != own_receipt}
 
 
-def _verdict(record, items):
-    """``accept``, ``revise`` or ``unresolved`` from a findings record and its item verdicts."""
+def _verdict(record, items, observations=()):
+    """``accept``, ``revise`` or ``unresolved`` from findings, item verdicts and ML observations."""
+    if any(type(row) is dict and row.get('status') == 'failed' for row in observations):
+        return 'revise'
+    if any(type(row) is not dict or row.get('status') != 'passed' for row in observations):
+        return 'unresolved'
     if type(record) is not dict:
         return 'unresolved'
     verdicts = [row.get('verdict') for row in record.get('item_verdicts') or () if type(row) is dict]
@@ -1201,7 +1264,8 @@
                            'ledger_code': getattr(exc, 'code', type(exc).__name__)})
             store.append('step-instruction-discharge-refused', {'step_id': state['acting']['id'],
                          'attempt': attempt, 'receipt': observed['instruction_receipt'], 'error': errors[-1]})
-    verdict = _verdict(final, items) if seat is not None or state['acting']['kind'] == 'review' else None
+    verdict = (_verdict(final, items, state.get('preflight', {}).get('ml_observations') or [])
+               if seat is not None or state['acting']['kind'] == 'review' else None)
     return {'validation': {'passed': not errors and not held, 'held': held, 'errors': errors, 'labels': labels,
                            'escalations': found, 'halts': halts, 'verdict': verdict,
                            'final_sha256': digest(final) if final is not None else None},
'''
FOLLOWUP_TEXT = r'''--- a/src/ravel/controller/step/graph.py
+++ b/src/ravel/controller/step/graph.py
@@ -582,7 +582,7 @@
 def _worker_preflight(state, store, ctx, run_dir, acting, card, found, run_inputs, evaluations):
     from ravel.workflow import agent_worker, transport_registry as tr
     from ravel.workflow.transports import cli_worker
-    ml_observations = _ml_observations(state)
+    observations = _ml_observations(state)
     seat = _seat(state)
     attempt = _attempt(state)
     problems = cards.ownership_errors(card, acting, found)
@@ -635,7 +635,8 @@
         subjects = [row['artifact'] if row['kind'] == 'run-input' else row['custody']['destination']
                     for row in rows]
         review_packet = review_projection.project(run_dir, card, key=f"{acting['id']}:{attempt}",
-            item={'role': card['id'], 'point_id': point_id, 'subject_sha256': subject_sha256}, subjects=subjects)
+            item={'role': card['id'], 'point_id': point_id, 'subject_sha256': subject_sha256,
+            'findings': observations}, subjects=subjects)
     else:
         pins.extend(copies)
     review = None
@@ -669,6 +670,6 @@
     return {'spec': worker, 'spec_sha256': digest(worker), 'selection': selection, 'outputs': outputs,
             'applied': applied, 'consults_pending': pending, 'dispatch_key': key, 'toolbelt': admitted,
             'review_packet': review_packet, 'inputs': input_ids,
-            'ml_observations': ml_observations}
+            'ml_observations': observations}
 
 
'''


class ObservationStore:
    """Small store with the record ids and scan shape used by RunStore."""

    def __init__(self, scan_shape='bare'):
        self.rows = {}
        self.scan_shape = scan_shape

    def append(self, kind, record):
        rows = self.rows.setdefault(kind, [])
        record_id = f'{kind}:{len(rows) + 1}'
        rows.append((record_id, deepcopy(record)))
        return record_id

    def read(self, kind, record_id):
        index = int(record_id.rsplit(':', 1)[1]) - 1
        row_id, record = self.rows[kind][index]
        if self.scan_shape == 'envelope':
            return {'id': row_id, 'record': deepcopy(record)}
        return {**deepcopy(record), '_record_id': row_id}

    def scan(self, kind):
        if self.scan_shape == 'envelope':
            return [{'id': record_id, 'record': deepcopy(record)}
                    for record_id, record in self.rows.get(kind, [])]
        return [{**deepcopy(record), '_record_id': record_id}
                for record_id, record in self.rows.get(kind, [])]


@pytest.fixture
def source_functions(tmp_path):
    """Extract actual controller function bodies and optionally apply the embedded patch."""
    source = ROOT / 'src/ravel/controller/step/graph.py'
    current_tree = ast.parse(source.read_text())
    has_helper = any(isinstance(node, ast.FunctionDef) and node.name == '_ml_observations'
                     for node in current_tree.body)
    if APPLY_FRAGMENT and not has_helper:
        destination = tmp_path / 'copy'
        source = destination / 'src/ravel/controller/step/graph.py'
        source.parent.mkdir(parents=True)
        source.write_bytes((ROOT / 'src/ravel/controller/step/graph.py').read_bytes())
        applied = subprocess.run(['git', 'apply', '-'], cwd=destination, input=PATCH_TEXT,
                                 text=True, capture_output=True, check=False)
        assert applied.returncode == 0, applied.stderr
    tree = ast.parse(source.read_text())
    wanted = {'_ml_observations', '_verdict'}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    namespace = {'deepcopy': deepcopy, '_store': lambda state: state['store']}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), 'exec'), namespace)
    return source, namespace


def _recorded_observations(store):
    spec = {'scope': 'bounded controller-observation fixture'}
    artifact = {'path': 'inputs/observations.json', 'sha256': hashlib.sha256(b'{}').hexdigest()}
    checks = {
        'check:ml-estimand-declared': {'verdict': 'fail', 'source': 'graph'},
        'check:ml-statistics-sizing': {'verdict': 'fail', 'source': 'validator',
                                       'validator': {'implementation': 'bounded-fixture'},
                                       'artifact': artifact},
        'check:ml-benchmark-localization': {'verdict': 'pass', 'source': 'validator',
                                            'validator': {'implementation': 'bounded-fixture'},
                                            'artifact': artifact},
    }
    bindings = rpc.record_ml_stage(store, spec=spec, stage='S1', result={'checks': checks})
    return spec, bindings


def _state(store, bindings):
    # The caller selected only one passing binding. The helper must recover every result
    # for that same frozen specification from the controller observation store.
    return {'store': store, 'acting': {'role': 'ml-reviewer', 'check_inputs': {
        'check:ml-benchmark-localization': bindings['check:ml-benchmark-localization']}},
        'step': {'check_inputs': {}}}


def _p13_projected_worker():
    """Read the exact new-side worker function from the existing projection patch."""
    patch = (ROOT / 'tests/fixtures/peer_contracts/worker-projection.patch').read_text().splitlines(keepends=True)
    files = {}
    current = None
    for line in patch:
        if line.startswith('--- a/'):
            current = line.removeprefix('--- a/').strip()
            files[current] = []
        elif line.startswith('@@'):
            files[current].append([])
        elif current is not None and files[current] and line[:1] in (' ', '+', '-'):
            files[current][-1].append(line)
    for body in files.get('src/ravel/controller/step/graph.py', []):
        before = ''.join(row[1:] for row in body if row[:1] in (' ', '-'))
        after = ''.join(row[1:] for row in body if row[:1] in (' ', '+'))
        if 'def _worker_preflight(' not in before:
            continue
        combined = after.replace(
            '    from ravel.workflow.transports import cli_worker\n',
            '    from ravel.workflow.transports import cli_worker\n'
            '    ml_observations = _ml_observations(state)\n', 1)
        assert 'ml_observations = _ml_observations(state)' in combined
        combined = combined.replace(
            "'review_packet': review_packet, 'inputs': input_ids}",
            "'review_packet': review_packet, 'inputs': input_ids,\n"
            "            'ml_observations': ml_observations}", 1)
        assert "'ml_observations': ml_observations" in combined
        return combined
    raise AssertionError('the projection patch has no worker-preflight new side')


@pytest.mark.parametrize('scan_shape', ['bare', 'envelope'])
def test_P13_review_item_carries_every_bound_ml_observation_partial_interface(
        source_functions, tmp_path, scan_shape):
    source, functions = source_functions
    helper = functions['_ml_observations']
    store = ObservationStore(scan_shape)
    _, bindings = _recorded_observations(store)
    observations = helper(_state(store, bindings))
    assert {row['check_id']: row['status'] for row in observations} == {
        'check:ml-estimand-declared': 'failed',
        'check:ml-statistics-sizing': 'failed',
        'check:ml-benchmark-localization': 'passed',
    }
    assert len({row['binding']['record_id'] for row in observations}) == 3
    assert all(row['result_sha256'] == broker.digest(rpc.observed_ml_result(
        store, row['binding'], check_id=row['check_id'])) for row in observations)

    # The controller's code-computed item is the exact document embedded by the real
    # review projection builder; no producer-supplied verdict is involved.
    card = {'id': 'ml-reviewer', 'sees': {'profile': 'blind', 'forbidden_inputs': []},
            'tools': {'read_paths': ['inputs/']}}
    item = {'point_id': 'fixture-review-point', 'role': 'ml-reviewer', 'n': 1,
            'subject_sha256': 'a' * 64, 'findings': observations}
    _, files = review_projection.build(tmp_path, card, item=item)
    packet = json.loads(next(raw for path, raw in files if path.endswith('/item.json')))
    assert packet['findings'] == observations


def test_P13_projection_followup_applies_after_first_fragment_and_projection_patch(tmp_path):
    target = tmp_path / 'src/ravel/controller/step/graph.py'
    target.parent.mkdir(parents=True)
    target.write_text('\n' * 581 + _p13_projected_worker())
    applied = subprocess.run(['git', 'apply', '-'], cwd=tmp_path, input=FOLLOWUP_TEXT,
                             text=True, capture_output=True, check=False)
    assert applied.returncode == 0, applied.stderr

    tree = ast.parse(target.read_text())
    worker = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                  and node.name == '_worker_preflight')
    calls = [node for node in ast.walk(worker) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == 'project']
    assert len(calls) == 1
    item = next(keyword.value for keyword in calls[0].keywords if keyword.arg == 'item')
    assert isinstance(item, ast.Dict)
    assert any(isinstance(key, ast.Constant) and key.value == 'findings'
               and isinstance(value, ast.Name) and value.id == 'observations'
               for key, value in zip(item.keys, item.values))
    returns = [node.value for node in ast.walk(worker) if isinstance(node, ast.Return)
               and isinstance(node.value, ast.Dict)]
    assert any({'ml_observations', 'review_packet'} <= {
        key.value for key in value.keys if isinstance(key, ast.Constant)} for value in returns)


def test_P13_worker_preflight_projects_authenticated_observations(tmp_path, projection_path,
                                                                  source_functions):
    graph, _, _, _ = projection_path
    worker_source = _p13_projected_worker()
    target = tmp_path / 'src/ravel/controller/step/graph.py'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('\n' * 581 + worker_source)
    applied = subprocess.run(['git', 'apply', '-'], cwd=tmp_path, input=FOLLOWUP_TEXT,
                             text=True, capture_output=True, check=False)
    assert applied.returncode == 0, applied.stderr
    worker_tree = ast.parse(target.read_text())
    worker_node = next(node for node in worker_tree.body if isinstance(node, ast.FunctionDef)
                       and node.name == '_worker_preflight')
    exec(compile(ast.Module(body=[worker_node], type_ignores=[]), str(target), 'exec'), graph)
    graph['_ml_observations'] = source_functions[1]['_ml_observations']
    graph['_store'] = lambda state: state['store']

    card = role_registry.load('ml-reviewer')
    run, state, rows = setup_run(tmp_path, card)
    store = ObservationStore(scan_shape='envelope')
    _, bindings = _recorded_observations(store)
    state['store'] = store
    state['acting']['role'] = 'ml-reviewer'
    state['acting']['check_inputs'] = {
        'check:ml-benchmark-localization': bindings['check:ml-benchmark-localization']}
    state['step']['check_inputs'] = {}
    prepared = graph['_worker_preflight'](state, store, {}, run, state['acting'], card,
                                         [], rows, {})
    manifest, artifacts = review_projection.load(prepared['review_packet'])
    packet = json.loads(artifacts['review/packets'])
    statuses = {row['check_id']: row['status'] for row in prepared['ml_observations']}
    assert statuses == {
        'check:ml-estimand-declared': 'failed',
        'check:ml-statistics-sizing': 'failed',
        'check:ml-benchmark-localization': 'passed',
    }
    assert packet['findings'] == prepared['ml_observations']
    assert manifest['role'] == 'ml-reviewer'
    assert source_functions[1]['_verdict'](
        {'item_verdicts': [{'verdict': 'pass'}]}, [], prepared['ml_observations']) == 'revise'


def test_P13_failed_observation_overrides_clean_reviewer_record(source_functions):
    _, functions = source_functions
    verdict = functions['_verdict']
    clean = {'item_verdicts': [{'verdict': 'pass'}]}
    assert verdict(clean, [], [{'check_id': 'check:ml-estimand-declared', 'status': 'failed'}]) == 'revise'


def test_failing_trainer_computation_reaches_the_reviewer(tmp_path, monkeypatch, wired_graph, source_functions):
    from ravel.workflow import review_independence
    from test_p13_ml_stage_wiring import NumericalEvaluator, NumericalValidator, context, fixture, start
    store = ObservationStore(scan_shape='envelope')
    monkeypatch.setattr(review_independence, 'controller_store', lambda root: store)
    spec = fixture(tmp_path)
    ctx = context(tmp_path, NumericalEvaluator(tmp_path, 'bad'), NumericalValidator())
    result = wired_graph._stage(ctx, start(ctx, spec), 'S2')
    assert result['blocking']
    state = {'store': store, 'acting': {'role': 'ml-reviewer', 'check_inputs': result['controller_checks']},
             'step': {'check_inputs': {}}}
    observations = source_functions[1]['_ml_observations'](state)
    assert {row['check_id'] for row in observations} == set(result['controller_checks']) == {
        'check:ml-statistics-sizing', 'check:ml-benchmark-localization'}
    assert all(row['status'] == 'failed' for row in observations)
    card = {'id': 'ml-reviewer', 'sees': {'profile': 'blind', 'forbidden_inputs': []},
            'tools': {'read_paths': ['inputs/']}}
    _, files = review_projection.build(tmp_path, card, item={'role': 'ml-reviewer', 'findings': observations})
    packet = json.loads(next(raw for path, raw in files if path.endswith('/item.json')))
    assert packet['findings'] == observations
    assert source_functions[1]['_verdict']({'item_verdicts': [{'verdict': 'pass'}]}, [],
                                          packet['findings']) == 'revise'


@pytest.mark.parametrize('status,expected', [('passed', 'accept'), ('inconclusive', 'unresolved')])
def test_P13_ml_review_accepts_only_complete_passing_observations(source_functions, status, expected):
    _, functions = source_functions
    clean = {'item_verdicts': [{'verdict': 'pass'}]}
    assert functions['_verdict'](clean, [], [{'check_id': 'check:ml-statistics-sizing', 'status': status}]) == expected


def test_P13_missing_ml_reviewer_bindings_are_an_inconclusive_observation(source_functions):
    _, functions = source_functions
    observations = functions['_ml_observations']({'store': ObservationStore(),
        'acting': {'role': 'ml-reviewer', 'check_inputs': {}}, 'step': {'check_inputs': {}}})
    assert len(observations) == 1
    assert observations[0]['status'] == 'inconclusive'
    assert observations[0]['binding'] is None
    assert functions['_verdict']({'item_verdicts': [{'verdict': 'pass'}]}, [], observations) == 'unresolved'


def test_P13_non_ml_role_without_observation_inputs_projects_no_rows(source_functions):
    _, functions = source_functions
    assert functions['_ml_observations']({'store': ObservationStore(),
        'acting': {'role': 'physics-critic'}, 'step': {'check_inputs': {}}}) == []


def test_P13_validate_node_supplies_preflight_observations_to_verdict(source_functions):
    source, _ = source_functions
    tree = ast.parse(source.read_text())
    validate_node = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                         and node.name == 'validate_node')
    calls = [node for node in ast.walk(validate_node) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name) and node.func.id == '_verdict']
    assert len(calls) == 1
    assert len(calls[0].args) == 3
    assert ast.unparse(calls[0].args[2]) == "state.get('preflight', {}).get('ml_observations') or []"


def test_P13_worker_preflight_and_projection_item_retain_observations(source_functions):
    source, _ = source_functions
    tree = ast.parse(source.read_text())
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    worker = ast.unparse(functions['_worker_preflight'])
    item_builder = ast.unparse(functions['review_items'])
    assert ("'ml_observations': ml_observations" in worker
            or "'ml_observations': observations" in worker)
    assert "'findings': _ml_observations(projection_state)" in item_builder
