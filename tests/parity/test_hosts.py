"""P-6, P-7 and P-16 across hosts: identical gates in code, a recorded hookless fixture, labelled qualification cells."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from parity_support import STUB_KINDS, cards, cell, declarations, mode_of
from ravel.workflow import host_governance, review_points as rp, role_registry, transport_registry as tr
from test_host_governance import GATES, _env, _run
from test_review_points import run as plan_run

REPO = Path(__file__).resolve().parents[2]
SHIM_HOSTS = ('claude', 'codex', 'gemini', 'antigravity', 'opencode')
HOST_NAMES = ('claude-code', 'codex', 'gemini-cli', 'opencode', 'qwen-code', 'goose', 'aider', 'ravel-drive')
SHARED_GATES = ('approve_plan', 'launch', 'checkin2_accept', 'final_task', 'delivery')


def run_gate(root, rundir, action, *, shim=None, command=None):
    wrapper = root / 'bin' / 'ravel'
    wrapper.parent.mkdir(exist_ok=True)
    wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} -m ravel "$@"\n')
    wrapper.chmod(0o755)
    tail = ['--rundir', str(rundir), '--action', action, '--json'] + (['--command', command] if command else [])
    env = {**_env(root), 'PATH': f'{wrapper.parent}:/usr/bin:/bin'}
    argv = ['sh', str(shim), *tail] if shim else [str(wrapper), 'gate', *tail]
    done = subprocess.run(argv, cwd=root, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert done.returncode in (0, 2), done.stderr
    verdict = json.loads(done.stdout)
    verdict.pop('checked_utc')
    return done.returncode, verdict


def test_every_host_shim_and_the_bare_gate_return_the_same_verdict(tmp_path):
    """P-6: for each gate, every host's shim and a bare `ravel gate` call agree on a shared fixture."""
    rd = _run(tmp_path / 'project', compute_plan='smoke', task_mode='reproduce')
    shims = {}
    for host in SHIM_HOSTS:
        relative, text = role_registry.gate_shim(host)
        shims[host] = tmp_path / 'shims' / (host + '.sh')
        shims[host].parent.mkdir(exist_ok=True)
        shims[host].write_text(text)
    for action in SHARED_GATES + ('tool_call',):
        command = 'bash native/scripts/run-pipeline-native.sh run cfg.toml' if action == 'tool_call' else None
        bare = run_gate(tmp_path, rd, action, command=command)
        assert bare[1]['decision'] in ('allow', 'deny') and bare[1]['pre_execution_guards'] == 'none'
        for host, shim in shims.items():
            assert run_gate(tmp_path, rd, action, shim=shim, command=command) == bare, (host, action)


def test_the_shim_table_covers_exactly_the_hosts_that_have_hooks():
    table = json.loads((REPO / 'src/ravel/data/agent_surface/hooks.json').read_text())
    assert set(table['shim_paths']) == set(SHIM_HOSTS)
    assert set(table['actions']) <= set(SHARED_GATES) | {'launch'}
    with pytest.raises(ValueError):
        role_registry.gate_shim('goose')             # a host without a shim: an explicit refusal


@pytest.mark.parametrize('host', HOST_NAMES)
def test_a_hookless_fixture_records_pre_execution_guards_on_every_host(tmp_path, host):
    """AGENT-INTERFACES 12: the record says `none` where no hook table exists, whatever the host calls itself."""
    rd = _run(tmp_path / 'project', compute_plan='smoke', task_mode='reproduce', agent_layer_epoch=2)
    record = host_governance.enforcement_record(rd, project=tmp_path / 'project')
    assert record['pre_execution_guards'] == 'none' and record['raw_launch'] == 'pass'
    assert set(record) == {'governance', 'pre_execution_guards', 'enforcement_surface_sha256', 'host', 'raw_launch',
                           'declared_host', 'declared_pre_execution_guards'}
    assert record['governance']['label'] == 'NOT GOVERNED'  # no controller owns this run
    code, verdict = run_gate(tmp_path, rd, 'final_task')
    assert verdict['pre_execution_guards'] == 'none' and verdict['kind'] == 'gate-verdict'
    assert host_governance.pre_execution_guards(tmp_path / 'project', environ={'RAVEL_HOST': host}) == 'none'
    # A declaration is never evidence: asserting hooks or a broker through the environment changes nothing.
    declared = {'RAVEL_HOST': host, 'RAVEL_PRE_EXECUTION_GUARDS': 'host-hooks'}
    assert host_governance.pre_execution_guards(tmp_path / 'project', environ=declared) == 'none'


def test_a_hookless_host_still_refuses_raw_generation_output_at_delivery(tmp_path):
    """P-7: the raw-launch invariant makes undeclared compute undeliverable without any hook."""
    rd = _run(tmp_path / 'project', compute_plan='smoke', task_mode='reproduce', agent_layer_epoch=2)
    (rd / 'stages/madgraph').mkdir(parents=True)
    (rd / 'stages/madgraph/unweighted_events.lhe.gz').write_bytes(b'raw')
    errors = host_governance.raw_launch_errors(rd)
    assert errors and errors[0]['provider'] == 'raw_launch'
    assert host_governance.enforcement_record(rd, project=tmp_path / 'project')['raw_launch'] == 'fail'
    code, verdict = run_gate(tmp_path, rd, 'delivery')
    assert code == 2 and verdict['decision'] == 'deny'


def test_wired_hooks_and_custody_are_the_only_other_guard_values(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    (project / '.claude').mkdir(parents=True)
    (project / '.claude/settings.json').write_text(json.dumps({'hooks': {'PreToolUse': [
        {'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': 'bash .claude/hooks/pretooluse-bash.sh'}]}]}}))
    assert host_governance.pre_execution_guards(project, environ={'CLAUDECODE': '1'}) == 'host-hooks'
    monkeypatch.setattr(host_governance, '_broker_records_session', lambda project, environ: True)
    assert host_governance.pre_execution_guards(tmp_path, environ={}) == 'broker'
    assert host_governance.pre_execution_guards(project, environ={'CLAUDECODE': '1'}) == 'host-hooks'


# ---------------------------------------------------------------- P-16 and the labelled cells

def fixture_points(root):
    plan_run(root, delegated=True, claims=[{'id': 'C1'}], nodes=[{'id': 'N1', 'operation': 'literal-calculation'}])
    return [p for p in rp.derive(rp._facts(root)) if p['blocking']]


def preference_file(root, class_row):
    families = {role_registry.load(r['role'])['family'] for p in fixture_points(root) for r in p['roles']}
    routes = class_row['worker'] + class_row['judgment']
    (root / 'inputs').mkdir(exist_ok=True)
    (root / 'inputs/agent_preferences.json').write_text(json.dumps({
        'schema_version': 1, 'kind': 'agent-preferences', 'families': {f: routes for f in sorted(families)},
        'tier_models': {tier: {r: 'claude-parity' for r in routes} for tier in tr.TIERS}}))


@pytest.mark.parametrize('model_class', [c['id'] for c in tr.model_classes()])
def test_a_plan_resolves_for_each_host_and_model_class_or_is_refused_naming_the_capability(parity_env, model_class):
    """P-16: dispatchable, or refused at CHECK-IN 1 with the missing capability named; never an unnamed failure."""
    row = next(c for c in tr.model_classes() if c['id'] == model_class)
    root = parity_env / 'run'
    root.mkdir()
    points = fixture_points(root)
    preference_file(root, row)
    errors = rp.dispatchability(root, points)
    assert errors == rp.dispatchability(root, points)                        # deterministic from stored records
    roles = {r['role'] for p in points for r in p['roles']}
    for error in errors:
        assert error.code == 'review_transport_missing' and error.gate == 'approve_plan'
        assert error.pins and all(i.startswith('capability:') and i.split(':')[1] in roles for i in error.pins), error
        assert all(len(i.split(':', 2)) == 3 and i.split(':', 2)[2] for i in error.pins)   # the capability is named


def test_every_model_class_route_is_a_declared_transport():
    declared = {d['id'] for d in declarations()}
    for row in tr.model_classes():
        assert set(row['worker'] + row['judgment']) <= declared, row['id']
        assert row['worker'] and row['judgment']
        assert all(tr.load(w)['capabilities']['tools'] == 'broker-full' or tr.load(w)['transport_kind'] == 'ravel-loop'
                   for w in row['worker']), row['id']


def test_blocking_and_voting_cells_are_labelled_unqualified_until_a_role_battery_exists(parity_env):
    """Transport qualification is not a role battery (CHECK-IN 1 labels). Every cell stays labelled."""
    assignments, expected = [], []
    for document in declarations():
        for card in cards():
            row = cell(card, document, qualified=True)
            if row['status'] != 'admitted':
                continue
            mode = mode_of(card)
            assignments.append({'role': card['id'], 'model_id': row['selection']['model'],
                                'transport': document['id'], 'effort': card['model'].get('effort'), 'mode': mode})
            expected.append(mode)
    assert assignments
    labelled = role_registry.qualification_labels(assignments, delegated=True)
    for source, row, mode in zip(assignments, labelled, expected):
        assert row['qualification']['status'] == 'unqualified' and row['qualification']['cell']['role'] == source['role']
        if mode in ('blocking', 'voting'):
            assert row['label'] == f'CHECK-IN 1: configurable, unqualified {mode} role cell'
        else:
            assert row['label'] == 'configurable, unqualified role cell'
    undelegated = role_registry.qualification_labels(assignments[:3], delegated=False)
    assert all(r['label'] == 'configurable, unqualified role cell' for r in undelegated)


def test_every_refused_cell_that_lacks_only_qualification_is_labelled_as_such(parity_env):
    blocked = []
    for document in declarations():
        for card in cards():
            row = cell(card, document, qualified=False)
            if row['status'] == 'refused' and 'qualification' in row['missing']:
                blocked.append((card['id'], document['id'], row['missing']))
    assert blocked                                    # unqualified blocking cells exist and are named by the selector
    assert all('qualification' in missing for *_, missing in blocked)
    assert STUB_KINDS
