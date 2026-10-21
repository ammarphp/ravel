"""Full-tier selected native tools and accepted-output synthesis on the real controller.

Uses the existing multi-part tool-selection fixture and its ordinary approval/resume path.
The construction worker is inert; measurement and authored symbolic tasks run natively.
No gate, native task validator, authority service or custody/adoption service is substituted.
"""
from pathlib import Path
import json

import pytest

from ravel.controller.ledger import state as ledger_state
from composition_toy_inputs import SCRIPT
from test_composition_tool_needs import (
    AGENTRIVET, MISSING, MULTI_FACTS, MULTI_PART, READY, approve_and_resume,
    drive_to_checkin1, execution_worker, installed_steps, planner_rounds, records,
)


def closed_execution_worker():
    """The existing selected forms, now carrying declared, approved native task inputs."""
    source = execution_worker()
    anchor = '    steps.append({"id": "combine-parts"'
    assert source.count(anchor) == 1
    preparation = '''
    for part in parts:
        operation = part.get("operation")
        if not operation:
            continue
        stem = "fit" if operation == "measurement" else "symbolic"
        names = [stem + "-task.json", "fit-data.json", "fit-normalization-ledger.json", "fit-yields.json"] if stem == "fit" else [
            stem + "-task.json", "symbolic-spec.txt", "symbolic-code.py", "submission.yaml", "grid.yaml", "trap_sweep.json"]
        part["inputs"] = [{"artifact": "inputs/" + n} for n in names]
        part["operation_task"] = {"materializer": "science-mode", "task_input": "inputs/" + stem + "-task.json",
                                  "result_output": part["outputs"][0]["path"]}
        if stem == "fit":
            part["outputs"].append({"path": "outputs/measurement.json", "kind": "inference", "required": True})
            part["check_inputs"] = {"check:physics.normalization_ledger.check": {
                "ledger": "inputs/fit-normalization-ledger.json", "delivered": "inputs/fit-yields.json"}}
        else:
            prefix = "outputs/authored-analysis/work/validation/"
            for name in ("normalization-ledger.json", "yields.json", "cutflow.json"):
                part["outputs"].append({"path": prefix + name, "kind": "table", "required": True})
            part["check_inputs"] = {
                "check:physics.normalization_ledger.check": {
                    "ledger": {"output": prefix + "normalization-ledger.json"},
                    "delivered": {"output": prefix + "yields.json"}},
                "check:validation.validate_cutflow": {
                    "signal": {"source": "output", "step": part["id"], "path": prefix + "cutflow.json", "type": "path"},
                    "routine": "toy-selection",
                    "sigma_pb": 2.0, "lumi_fb": .001, "tables_dir": "inputs", "grid": "toy",
                    "m_parent": 100, "m_lsp": 1, "srs": "X", "driving_sr_override": "X"}}
'''
    source = source.replace(anchor, preparation + anchor)
    source = source.replace('if step.get("kind") == "derive":',
                            'if step.get("kind") in ("derive", "synthesize"):')
    source = source.replace('governed(workspace, step) if step.get("kind") == "derive"',
                            'governed(workspace, step) if step.get("kind") in ("derive", "synthesize")')
    anchor = '    reads, consumed = governed(workspace, step)'
    assert source.count(anchor) == 1
    source = source.replace(anchor, '''
    if step.get("kind") == "synthesize":
        block = between(prompt, "== Inputs (by digest) ==\\n", "\\n== Output contract") or ""
        admitted = [json.loads(row) for row in re.split(r"(?m)^- ", block)[1:]]
        current = {row["artifact"]: row["sha256"] for row in admitted}
        step["inputs"] = [{**row, "sha256": current.get(row["artifact"], row.get("sha256"))}
                          for row in step["inputs"]]
''' + anchor)
    anchor = '    pins = {}\n    for row in step.get("inputs") or ():'
    assert source.count(anchor) == 1
    source = source.replace(anchor, '''
    if step.get("kind") == "synthesize":
        manifest_path = "inputs/packet/manifest.json"
        manifest = json.loads((workspace / manifest_path).read_text())
        projected = {(r["source_path"], r["source_sha256"]): r for r in manifest["artifacts"]}
        reads, consumed = [manifest_path], []
        for ref in step["inputs"]:
            path = "steps/" + ref["artifact"].replace(":", "/", 1)
            pin = {"path": path, "sha256": ref["sha256"]}
            row = projected[(path, ref["sha256"])]
            copy = workspace / "inputs/packet" / row["path"]
            assert row["sha256"] == ref["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()
            reads.append(copy.relative_to(workspace).as_posix())
            consumed.append(pin)
        return reads, consumed
''' + anchor)
    anchor = '    result = {"schema_version": 1, "kind": "inert-result", "value": 1.0, "uncertainty": 0.1}'
    assert source.count(anchor) == 1
    source = source.replace(anchor, '''
    if step.get("id") == "serve-routine-construction" and step.get("kind") == "author":
        return {"schema_version": 1, "kind": "inert-tool-effect", "effects": 1}
''' + anchor)
    return source


def native_inputs():
    from ravel.workflow.trap_sweep import build, TRAP_IDS
    namespace = {}
    exec(SCRIPT, namespace)
    _, audit = namespace['toy_inputs']('toy-selection', 'unused', 1)
    ids = ['a', 'b']
    def vector(values):
        return {'values': values, 'bin_ids': ids, 'unit': 'events'}
    # Thirty unit-weight rows partitioned into the two actual SM-prediction bins.
    ledger = json.loads(audit['validation/normalization-ledger.json'])
    ledger['sigma']['value'] = 30.0
    ledger['generated'] = {'sumw': 30.0, 'sumw2': 30.0}
    ledger['selected'] = {'toy-region': {'sumw': [10.0, 20.0], 'sumw2': [10.0, 20.0]}}
    result = {
        'fit-task.json': {'schema_version': 1, 'input': 'fit-data.json',
                          'inference': 'goodness_of_fit', 'signal_strength': 1.0},
        'fit-data.json': {'schema_version': 1, 'analysis_id': 'synthetic-gaussian-control',
            'quantity': {'axes': [{'name': 'mass', 'unit': 'GeV'}],
                        'bins': [{'id': 'a', 'low': [0], 'high': [1]}, {'id': 'b', 'low': [1], 'high': [3]}],
                        'representation': 'integrated', 'normalization': 'absolute', 'unit': 'events'},
            'data': vector([11, 19]), 'sm': vector([10, 20]), 'signal': vector([2, 1]),
            'experimental_covariance': {'bin_ids': ids, 'matrix': [[4, 1], [1, 9]], 'unit': '(events)^2'},
            'covariance_policy': 'experimental_only', 'overlap': {'policy': 'single_measurement'}, 'constraints': []},
        'symbolic-task.json': {'purpose': 'Execute the supplied bounded symbolic toy derivation.',
            'specification': 'symbolic-spec.txt', 'code': 'symbolic-code.py',
            'io_contract': {'inputs': [], 'outputs': [{'path': name, 'kind': 'json',
                'postconditions': [{'check': 'exists'}]} for name in (
                    'symbolic-effect.json', 'validation/normalization-ledger.json',
                    'validation/yields.json', 'validation/cutflow.json')]}, 'budget': 1, 'timeout_seconds': 30},
        'symbolic-spec.txt': 'Derive the toy expression x+x with the symbolic library. No scientific claim.\n',
        'symbolic-code.py': SCRIPT + '\nfrom pathlib import Path\nfrom sympy import symbols\n'
                            'x = symbols("x")\n'
                            'Path("symbolic-effect.json").write_text(json.dumps({"effects": 1, "expression": str(x+x)}))\n'
                            '_, files = toy_inputs("toy-selection", "unused", 1)\n'
                            'for name in ("normalization-ledger.json", "yields.json", "cutflow.json"):\n'
                            '    path = Path("validation") / name\n'
                            '    path.parent.mkdir(exist_ok=True)\n'
                            '    path.write_text(files["validation/" + name])\n',
        'fit-normalization-ledger.json': ledger,
        'fit-yields.json': {'toy-region': [10.0, 20.0]},
        'submission.yaml': audit['validation/tables/submission.yaml'],
        'grid.yaml': audit['validation/tables/grid.yaml'],
        'trap_sweep.json': build({'verdicts': [{'id': trap, 'hit': False,
            'evidence': 'Supplied deterministic finite toy: unit weights, explicit disjoint bins, no event generation, '
                        'no model decays, no exclusion or experimental interpretation; symbolic x+x only.'}
                                              for trap in TRAP_IDS]}),
    }
    assert result['fit-data.json']['sm']['values'] == result['fit-yields.json']['toy-region']
    return result


@pytest.mark.parametrize('construction_available', [True, False], ids=['tool-present', 'tool-missing'])
def test_approved_selected_parts_execute_and_accepted_outputs_reach_synthesis(
        tmp_path, monkeypatch, construction_available):
    store, observation, stderr = drive_to_checkin1(tmp_path, monkeypatch,
        rows={**MULTI_FACTS, AGENTRIVET: READY if construction_available else MISSING}, request=MULTI_PART,
        worker=closed_execution_worker(), supplied_files=native_inputs())
    try:
        steps = {s['id']: s for s in installed_steps(store)}
        parts = {sid: s for sid, s in steps.items() if sid.startswith('serve-')}
        assert len(parts) == 3 and 'combine-parts' in steps
        assert {sid: (s.get('role'), s.get('operation')) for sid, s in parts.items()} == {
            'serve-routine-construction': ('routine-constructor', None) if construction_available else
                                          ('analysis-author', 'authored-analysis'),
            'serve-global-fit': ('inference', 'measurement'),
            'serve-symbolic-model-building': ('analysis-author', 'authored-analysis')}
        selection = records(store, 'tool-selection')[-1]
        assert selection['passed'] and all(n['status'] == 'served' for n in selection['needs'])
        from ravel.controller import engagement
        assert engagement.effective_decision(store)['tier'] == 'full'
        observation, stderr = approve_and_resume(store, observation, stderr)
        outcomes = {r['step_id']: r for r in records(store, 'step-outcome')}
        assert all(outcomes.get(sid, {}).get('status') == 'completed' for sid in [*parts, 'combine-parts']), (
            outcomes, records(store, 'qualified-ending'), planner_rounds(store))
        for sid, part in parts.items():
            if part['kind'] == 'operate':
                launched = [r for r in records(store, 'step-launch') if r.get('step_id') == sid]
                assert [r['phase'] for r in launched] == ['started', 'finished'], launched
                assert launched[-1]['exit_status'] == 0
            else:
                assert any(r.get('step_id') == sid for r in records(store, 'step-dispatch'))
        from ravel.controller.step.custody import custody_index
        accepted = custody_index(store)
        expected = {r['artifact'] for r in steps['combine-parts']['inputs']}
        assert expected == {sid + ':' + part['outputs'][0]['path'] for sid, part in parts.items()}
        assert all(accepted[a]['status'] == 'accepted' for a in expected)
        for sid, part in parts.items():
            artifact = sid + ':' + part['outputs'][0]['path']
            body = json.loads((Path(store.run_dir) / accepted[artifact]['destination']).read_text())
            if part.get('operation') == 'measurement':
                assert body['kind'] == 'supplied_gaussian_measurement' and body['status'] == 'passed'
                assert body['goodness_of_fit']['sm']['chi2'] == pytest.approx(15 / 35)
            elif part.get('operation') == 'authored-analysis':
                assert body['kind'] == 'authored-analysis' and body['status'] == 'passed'
                effect, = [row for row in body['outputs'] if row['path'].endswith('/symbolic-effect.json')]
                path = Path(store.run_dir) / 'steps' / sid / 'attempts/1/outputs' / effect['path']
                assert json.loads(path.read_text()) == {'effects': 1, 'expression': '2*x'}
                yields = Path(store.run_dir) / 'steps' / sid / 'attempts/1/outputs/authored-analysis/work/validation/yields.json'
                assert json.loads(yields.read_text()) == {'X': [1.0]}
            else:
                assert body['kind'] == 'inert-tool-effect' and body['effects'] == 1
        combined = accepted['combine-parts:outputs/combined.json']
        assert combined['status'] == 'accepted' and set(combined['inputs']) == expected
        result = json.loads((Path(store.run_dir) / combined['destination']).read_text())
        consumed = {(r['path'], r['sha256']) for r in result['inputs']}
        assert consumed == {(accepted[a]['destination'], accepted[a]['sha256']) for a in expected}
        assert not (tmp_path / 'sentinel-effect').exists()
        assert not any(s.get('operation') == 'external-workflow' for s in steps.values())
        assert not any('snakemake' in str(r).lower() for r in records(store, 'step-launch'))
        print('COMPOSED_EXECUTION=' + json.dumps({'parts': sorted(parts), 'accepted_inputs': sorted(expected),
                                                  'synthesis': 'completed', 'sentinel_effects': 0}))
    finally:
        ledger_state.forget(store)
