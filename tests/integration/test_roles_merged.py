"""B1 merged-tree acceptance, using the tree's real providers and declarations.

No vendor CLI, physics tool, qualification, worker credit or custody receipt is
produced here. Qualification is per host, so T-M1 is a selection control: the
transport probes and the qualification record below are synthetic records stored
under a temporary state directory and read back by the registry's stored-record
path. They are never shipped and never claim a live run. Missing prerequisite
branches are reported separately from the two named decision-gate handoffs.
"""
from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TABLE_START = '<!-- B1 T-M1 truth table: start -->'
TABLE_END = '<!-- B1 T-M1 truth table: end -->'
EXECUTABLE_SHA256 = hashlib.sha256(b'B1 synthetic selection executable').hexdigest()
VOTING_ROUTE = 'claude-cli-worker'


def _module(name, *, handoff=None):
    qualified = 'ravel.workflow.' + name
    if importlib.util.find_spec(qualified) is None:
        if handoff:
            pytest.xfail(handoff + ': prerequisite module not yet merged: ' + name)
        pytest.skip('merged acceptance pending: prerequisite module not yet merged: ' + name)
    module = importlib.import_module(qualified)
    assert Path(module.__file__).resolve().is_relative_to(ROOT / 'src'), qualified
    return module


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _preferences(registry, declarations):
    # Claude first is the contracted voting route. Every A declaration follows.
    order = ['claude-cli-worker'] + sorted(d['id'] for d in declarations if d['id'] != 'claude-cli-worker')
    tiers, model_families = {}, {}
    for document in declarations:
        for model in document['models']:
            identity = model['id'] if '{' not in model['id'] else document['id'] + '-fixture-model'
            model_families[identity] = model['family'] if model['family'] != 'any' else 'anthropic'
            for tier in model['tiers']:
                tiers.setdefault(tier, {}).setdefault(document['id'], identity)
    return {'schema_version': 1, 'kind': 'agent-preferences',
            'families': {card['family']: order for card in registry.all_cards()},
            'tier_models': tiers, 'model_families': model_families}


def _selection_probes(transport, declarations):
    """Synthetic confirmed carrier flags; declaration qualification stays intact."""
    result = {}
    for document in declarations:
        if document['transport_kind'] not in transport.CLI_KINDS:
            continue
        result[document['id']] = {
            'schema_version': 1, 'kind': 'transport-probe', 'transport_id': document['id'],
            'declaration_sha256': transport.declaration_sha256(document),
            'cli_version': 'synthetic-selection-control', 'help_sha256': '0' * 64,
            'flags': {flag: 'confirmed' for flag in transport.template_flags(document)},
            'capabilities_confirmed': {key: bool(document['capabilities'][key])
                                       for key in transport.BOOLEAN_CAPABILITIES},
            'unusable': [], 'probed_utc': '2026-10-11T00:00:00Z',
            'executable_path': '/synthetic/b1-selection-control',
            'executable_sha256': EXECUTABLE_SHA256, 'exit_status': 0}
    return result


def store_selection_records(transport, qualified=(VOTING_ROUTE,)):
    """Write the synthetic probes, and qualification records for ``qualified``, to the state dir.

    Each qualification record matches its stored probe and the shipped declaration
    digest, so only the registry's own record reader can raise the route's status.
    """
    declarations = transport.all_declarations()
    probes = _selection_probes(transport, declarations)
    for identity, record in probes.items():
        _write(transport.probe_path(identity), record)
    for identity in qualified:
        document = transport.load(identity)
        path = transport.qualification_path(identity)
        _write(path, {
            'schema_version': 1, 'kind': 'transport-qualification', 'transport_id': identity,
            'status': 'live_qualified', 'record_path': str(path),
            'executable_path': probes[identity]['executable_path'], 'executable_sha256': EXECUTABLE_SHA256,
            'declaration_sha256': transport.declaration_sha256(document),
            'probe_sha256': transport.digest(probes[identity]),
            'receipt': {'synthetic': 'B1 selection control'}, 'observed': {}, 'steps': [],
            'rundir': '/synthetic/b1-selection-control', 'qualified_utc': '2026-10-11T00:00:00Z'})
    return probes


def truth_table_rows(registry, transport):
    """Return exact select outcomes from the stored records; retain all refusal reasons."""
    declarations = transport.all_declarations()
    preferences = _preferences(registry, declarations)
    probes = {d['id']: transport.read_probe(d['id']) for d in declarations if d['transport_kind'] in transport.CLI_KINDS}
    extra = {'executables': {identity: EXECUTABLE_SHA256 for identity in probes}}
    rows = []
    for card in registry.all_cards():
        # Previously assigned families are controlled independently; no receipt
        # or scientific independence is credited by these selection controls.
        assigned = {role: {'family': 'openai', 'transport_id': 'http-responses', 'model': 'gpt-fixture'}
                    for role in card['model'].get('distinct_family_from', [])}
        try:
            selected = transport.select(card, preferences, assigned=assigned, **extra)
        except transport.TransportRefusal as exc:
            rows.append({'role': card['id'], 'voting': card['independence']['kind'] == 'voting',
                         'route': 'refused', 'missing': sorted(set(exc.missing))})
        else:
            rows.append({'role': card['id'], 'voting': card['independence']['kind'] == 'voting',
                         'route': selected['transport_id'], 'missing': []})
    return rows


def truth_table_markdown(rows):
    lines = ['| Role | Voting | Selected route | Missing |', '|---|---|---|---|']
    for row in rows:
        missing = json.dumps(row['missing'], ensure_ascii=False, separators=(',', ':'))
        lines.append(f"| `{row['role']}` | {'yes' if row['voting'] else 'no'} | `{row['route']}` | `{missing}` |")
    return '\n'.join(lines) + '\n'


def test_shipped_voting_route_does_not_claim_live_qualification():
    shipped = json.loads((ROOT / 'src/ravel/data/transports/claude-cli-worker.json').read_text())
    assert shipped['id'] == VOTING_ROUTE
    assert shipped['qualification']['status'] != 'live_qualified'


def test_t_m1_real_transport_truth_table_matches_recorded_roles(tmp_path, monkeypatch):
    registry = _module('role_registry')
    transport = _module('transport_registry')
    if not hasattr(transport, 'is_voting') or not transport.is_voting({'independence': {'kind': 'voting'}}):
        pytest.skip('merged acceptance pending: the canonical voting binding is absent')
    assert 'executables' in inspect.signature(transport.select).parameters
    monkeypatch.setenv('RAVEL_STATE_DIR', str(tmp_path / 'state'))
    probes = store_selection_records(transport, qualified=())
    # Without a stored qualification record the shipped declarations select no route at all.
    unqualified = truth_table_rows(registry, transport)
    assert all(row['route'] == 'refused' for row in unqualified), unqualified
    assert all('qualification' in row['missing'] for row in unqualified if row['voting']), unqualified
    store_selection_records(transport)
    document = transport.load(VOTING_ROUTE)
    assert transport.read_qualification(document, probes[VOTING_ROUTE]) is not None
    assert transport.qualification_status(document, probes[VOTING_ROUTE]) == 'live_qualified'
    rows = truth_table_rows(registry, transport)
    assert any(row['voting'] for row in rows)
    voting_failures = [row for row in rows if row['voting'] and row['route'] != VOTING_ROUTE]
    assert not voting_failures, ('STOP B1 T-M1: release has no conforming declared voting path; '
                                 'coordinator decision required: ' + json.dumps(voting_failures))
    assert all((row['route'] == 'refused') == bool(row['missing']) for row in rows), rows
    text = (ROOT / 'docs/reference/roles.md').read_text()
    assert text.count(TABLE_START) == text.count(TABLE_END) == 1
    recorded = text.split(TABLE_START + '\n', 1)[1].split(TABLE_END, 1)[0]
    assert recorded.encode() == truth_table_markdown(rows).encode(), 'T-M1 exact missing-set table differs'


def delegated_plan():
    from ravel.setup import manifest as mf
    signatures = json.loads((ROOT / 'src/ravel/data/operation_signatures.json').read_text())['operations']
    release = mf.load(ROOT)[0]
    # Tools held out of the release have no consult role, as role_registry.validate_registry declares.
    tools = sorted({tool for signature in signatures.values() for tool in signature.get('tools', [])
                    if not mf.release_mentions(release, 'consult-' + tool)})
    nodes = [{'id': 'N1', 'operation': 'literal-calculation', 'rung': 'smoke'}]
    for number, kind in enumerate(('spec', 'cards', 'model', 'statistical_model', 'routine'), start=2):
        nodes.append({'id': f'N{number}.author', 'operation': 'literal-calculation',
                      'artifact_kind': kind, 'authored': {'purpose': 'synthetic fixture'}, 'rung': 'smoke'})
    # review_points derives literal consult-<node.tool> names. Cover the exact
    # registered signature vocabulary, including vendor case and spaces; do
    # not make the operation fallback invent additional tool identities.
    for number, tool in enumerate(tools, start=10):
        nodes.append({'id': f'N{number}.consult', 'operation': 'literal-calculation',
                      'tool': tool, 'status': 'failed', 'rung': 'smoke'})
    return {'agent_layer_epoch': 2, 'delegated': True, 'nodes': nodes, 'edges': [],
            'claims': [{'id': 'C1', 'kind': 'document'}]}


def _run(root, plan=None):
    root.mkdir(parents=True, exist_ok=True)
    pin = _write(root / 'inputs/plan.json', plan or delegated_plan())
    pin['path'] = 'inputs/plan.json'
    _write(root / 'inputs/task_contract.json', {
        'agent_layer_epoch': 2, 'delegated': True, 'request_plan': pin,
        'task_mode': 'calculate', 'compute_plan': 'smoke'})
    _write(root / 'run_state.json', {'schema_version': 1, 'session_id': ''})
    return root


def test_t_m2_derived_roles_resolve_and_approve_plan_does_not_lose_cards(tmp_path):
    registry = _module('role_registry')
    review = _module('review_points', handoff='role-card loading')
    decision = _module('decision_gate', handoff='role-card loading')
    _module('transport_registry')
    facts = delegated_plan()
    points = review.derive(facts)
    names = {role['role'] for point in points for role in point['roles']}
    expected_consults = {'consult-' + node['tool'] for node in facts['nodes'] if node.get('tool')}
    assert expected_consults <= names
    resolved = registry.resolve_names(names)
    assert set(resolved) == names
    assert all(registry.load(name)['id'] == identity for name, identity in resolved.items())
    root = _run(tmp_path / 'run', facts)
    errors = decision.check(root, 'approve_plan', {'kind': 'approve_plan', 'digest': '0' * 64})
    missing_cards = [error for error in errors if 'Required role card is unavailable' in error.message]
    if missing_cards and 'role_registry' not in inspect.getsource(review.dispatchability):
        pytest.xfail('dispatchability must load cards through role_registry.load()')
    assert not missing_cards, missing_cards


def _environment(tmp_path):
    env = {key: value for key, value in os.environ.items() if key not in (
        'CLAUDE_CODE_SESSION_ID', 'CLAUDECODE', 'RAVEL_SESSION_ID', 'CLAUDE_PROJECT_DIR',
        'RAVEL_HOST', 'RAVEL_PRE_EXECUTION_GUARDS')}
    for variable, directory in [('HOME', 'home'), ('MPLCONFIGDIR', 'mpl'), ('RAVEL_STATE_DIR', 'state')]:
        target = tmp_path / directory
        target.mkdir(parents=True, exist_ok=True)
        env[variable] = str(target)
    env.update(PYTHONPATH=str(ROOT / 'src'), RAVEL_PYTHON=sys.executable)
    return env


def test_t_m3_gate_cli_executor_provider_is_active(tmp_path):
    decision = _module('decision_gate', handoff='executor provider')
    _module('transport_registry')
    _module('host_gate')
    executor = _module('production_executor')
    # The executor provider replaced the prerequisite control that expected it to be inactive.
    row = next(r for r in decision.providers('launch') if r['id'] == 'executor')
    assert row['active'] and row['module'] == executor.__name__ and callable(executor.gate_errors), row
    root = _run(tmp_path / 'run', {'nodes': [], 'edges': [], 'claims': []})
    done = subprocess.run([sys.executable, '-m', 'ravel', 'gate', '--action', 'launch',
                           '--rundir', str(root), '--json'], cwd=tmp_path,
                          env=_environment(tmp_path), capture_output=True, text=True)
    assert done.returncode == 2, done.stdout + done.stderr
    verdict = json.loads(done.stdout)
    errors = [error for error in verdict['errors'] if error['provider'] == 'executor']
    assert errors == [], verdict


@pytest.mark.parametrize('kind', ['registry', 'override', 'profile', 'shim'])
def test_t_m4_role_authority_changes_checkin_fingerprint_and_is_write_protected(tmp_path, kind):
    registry = _module('role_registry')
    governance = _module('host_governance')
    if not hasattr(governance, 'SURFACE_EXTENSIONS'):
        pytest.skip('merged acceptance pending: SURFACE_EXTENSIONS is absent')
    project = tmp_path / 'project'
    roles = project / 'src/ravel/data/roles'
    _write(roles / 'registry.json', registry.registry_document())
    for surface in registry.SURFACES:
        for relative, content in registry.render(surface).items():
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    override = roles / 'cards/generator.json'
    _write(override, registry.load('generator'))
    paths = {'registry': roles / 'registry.json', 'override': override,
             'profile': project / registry.profile_paths('claude')['physics-critic'],
             'shim': project / registry.gate_shim('claude')[0]}
    path = paths[kind]
    owned = registry.owned_paths(project)
    assert path in {Path(value) for value in owned.values()}, (kind, owned)
    assert path in {Path(value) for value in governance.surface_files(project).values()}, (kind, governance.surface_files(project))
    root = _run(tmp_path / 'run')
    before = governance.record_checkin1_surface(root, project=project)
    assert 'role_registry_sha256' in before
    path.write_bytes(path.read_bytes() + b'\n')
    after = governance.record_checkin1_surface(root, project=project)
    assert before['enforcement_surface_sha256'] != after['enforcement_surface_sha256']
    marker = project / 'logs/.route-pending-B1-T-M4'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('synthetic physics session\n')
    payload = {'tool_name': 'Edit', 'session_id': 'B1-T-M4',
               'tool_input': {'file_path': str(path)}}
    env = _environment(tmp_path)
    env['CLAUDE_PROJECT_DIR'] = str(project)
    done = subprocess.run(['bash', str(ROOT / '.claude/hooks/protect-enforcement.sh')],
                          input=json.dumps(payload), cwd=project, env=env,
                          capture_output=True, text=True)
    assert done.returncode == 2, (kind, done.stdout, done.stderr)


def test_t_m4_governance_first_registers_role_surface_extension(tmp_path):
    _module('host_governance')
    code = ('from ravel.workflow import host_governance as governance\n'
            'from ravel.workflow import role_registry as registry\n'
            'assert registry.owned_paths in governance.SURFACE_EXTENSIONS\n')
    done = subprocess.run([sys.executable, '-c', code], cwd=tmp_path,
                          env=_environment(tmp_path), capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
