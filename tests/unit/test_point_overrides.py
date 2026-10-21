"""Fictional point repairs, exact authority, retained attempts and masked holes."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.workflow import point_overrides as po
from ravel.workflow import scan_orchestrator as scan
from ravel.workflow import study_grid as sg
from ravel.workflow import allocation_study as al
from test_study_grid import grid, finish, write
from test_named_scan_cards import contract


def authority(tmp_path, monkeypatch, context, fields):
    root = tmp_path / 'parent-authority'
    path = write(root / 'inputs/policy.json', {'point_override_scope': {
        'context_sha256': context, 'fields': fields}})
    files = {'inputs/policy.json': al._sha(path)}
    monkeypatch.setattr(al, '_approval', lambda rd, route, rung: (None, files) if Path(rd) == root else (None, {}))
    return dict(rundir=str(root), route='checkin1', rung='scan', approval_files=files)


def proposal(tmp_path, approval, changes=None):
    evidence = tmp_path / 'diagnostic.txt'
    evidence.write_text('integration did not converge')
    return dict(changes=changes or {'/parameters/accuracy': .01}, reason='integration-failure',
                diagnostics=[po.pin(evidence)], approval=approval)


def planned(tmp_path):
    spec = contract(tmp_path)
    Path(spec['template_toml']).write_text('[parameters]\nvalue = 0\naccuracy = 0.1\n')
    path = write(tmp_path / 'scan.json', spec)
    scan.cmd_plan(SimpleNamespace(spec=str(path), dry_run=False))
    directory = Path(spec['run_root']) / (spec['run_prefix'] + '_SCAN')
    _, manifest = scan.load_manifest(str(directory))
    return directory, manifest


def test_native_override_identity_harvest_resume_and_no_interpolation(tmp_path, monkeypatch):
    directory, manifest = planned(tmp_path)
    approval = authority(tmp_path, monkeypatch, scan.override_context(manifest),
        {'/parameters/accuracy': {'values': [.01], 'physics': False}})
    point = manifest['points'][0]
    original = Path(point['run_dir']) / point['config']
    original_bytes = original.read_bytes()
    record = scan.record_override(directory, point['tag'], proposal(tmp_path, approval))
    _, current = scan.load_manifest(str(directory))
    effective = current['points'][0]
    assert effective['config'] != point['config']
    assert po.verify(record, Path(point['run_dir']) / effective['config']) == record['receipt_sha256']
    assert original.read_bytes() == original_bytes
    result = write(Path(point['run_dir']) / effective['output_directory'] / 'response.json', {'value': 7})
    with pytest.raises(ValueError, match='receipt'):
        scan.harvest_point(effective)
    write(result.parent / 'native_execution_result.json', {'point_receipt_sha256': record['receipt_sha256'],
        'quantity_outputs': [po.pin(result)]})
    harvested = scan.harvest_point(effective)
    assert harvested['overridden'] and harvested['regime'] == 'integration-failure'
    assert harvested['receipt_sha256'] == record['receipt_sha256']
    scan.cmd_assemble(SimpleNamespace(scandir=str(directory), out=None))
    output = json.loads((directory / 'requested.json').read_text())
    assert output['n_missing'] == 1 and len(output['points']) == 1
    assert len(output['point_population']) == 2
    assert output['point_population'][1]['status'] == 'missing'
    # A failed retry selects the persisted effective config, not the original template.
    result.unlink()
    state = Path(point['run_dir']) / 'logs/STATUS.txt'
    state.parent.mkdir(); state.write_text('FAIL\n')
    import ravel.physics.native_pipeline as native
    from ravel.workflow import gate_wiring
    selected = []
    monkeypatch.setattr(native, 'build_execution_plan', lambda root, config, **kw: selected.append(config) or {})
    monkeypatch.setattr(gate_wiring, 'dispatch_permitted', lambda *a: (True, None))
    monkeypatch.setattr(gate_wiring, 'prioritize_pending', lambda root, rows: rows)
    monkeypatch.setattr(scan, 'launch_point', lambda *a, **kw: None)
    args = SimpleNamespace(scandir=str(directory), max=1, backend='native', resume=True, go=False)
    scan.cmd_launch(args)
    assert selected == [effective['config']]


def test_out_of_scope_requires_exact_approved_amendment(tmp_path, monkeypatch):
    directory, manifest = planned(tmp_path)
    approval = authority(tmp_path, monkeypatch, scan.override_context(manifest),
        {'/parameters/accuracy': {'values': [.001], 'physics': False}})
    point = manifest['points'][0]
    request = proposal(tmp_path, approval)
    with pytest.raises(ValueError, match='requires an amendment'):
        scan.record_override(directory, point['tag'], request)
    root = tmp_path / 'amendment'
    pin = write(root / 'inputs/policy.json', {'point_override_amendment': {
        'context_sha256': scan.override_context(manifest),
        'point_id': point['tag'], 'changes': request['changes'], 'physics_fields': []}})
    amendment_files = {'inputs/policy.json': al._sha(pin)}
    old = al._approval
    monkeypatch.setattr(al, '_approval', lambda rd, route, rung: (None, amendment_files) if Path(rd) == root else old(rd, route, rung))
    request['amendment'] = dict(rundir=str(root), route='checkin1', rung='scan', approval_files=amendment_files)
    record = scan.record_override(directory, point['tag'], request)
    assert record['authority'] == 'amendment'
    pin.write_text('{}')
    # Use the real byte verifier seam as well as the mocked execution approval.
    monkeypatch.setattr(al, '_approval', lambda rd, route, rung: (None, {'inputs/policy.json': al._sha(pin)}) if Path(rd) == root else old(rd, route, rung))
    with pytest.raises(ValueError, match='approval changed'):
        po.verify(record)


def test_physics_settings_require_actual_neighbour_comparison(tmp_path, monkeypatch):
    directory, manifest = planned(tmp_path)
    approval = authority(tmp_path, monkeypatch, scan.override_context(manifest),
        {'/parameters/accuracy': {'values': [.01], 'physics': True}})
    point, neighbour = manifest['points']
    request = proposal(tmp_path, approval)
    with pytest.raises(ValueError, match='neighbour comparison'):
        scan.record_override(directory, point['tag'], request)
    default = write(Path(neighbour['run_dir']) / 'output/response.json', {'value': 9})
    varied = write(tmp_path / 'comparison-result.json', {'value': 8.9})
    arm_a = write(tmp_path / 'default-arm.json', {'point_id': neighbour['tag'], 'changes': {}, 'result': po.pin(default)})
    arm_b = write(tmp_path / 'override-arm.json', {'point_id': neighbour['tag'], 'changes': request['changes'], 'result': po.pin(varied)})
    request['comparison'] = {'neighbour_id': neighbour['tag'], 'default': po.pin(arm_a),
        'override': po.pin(arm_b), 'assessment': 'Supplied comparison differs by 0.1; retained for review.'}
    record = scan.record_override(directory, point['tag'], request)
    assert record['physics_fields'] == ['/parameters/accuracy']
    assert record['comparison']['neighbour_id'] == neighbour['tag']
    varied.write_text('{}')
    assert po.verify(record) == record['receipt_sha256']
    # Original comparison and retry logs can change; admitted archived bytes cannot.
    archived_arm = sg.read_json(Path(record['comparison']['override']['path']))
    Path(archived_arm['result']['path']).write_text('{}')
    with pytest.raises(ValueError, match='evidence or settings changed'):
        po.verify(record)


def test_grid_override_reuses_settings_and_marks_attempt_harvest_and_plot(grid, tmp_path, monkeypatch):
    doc = sg.read_json(grid[0])
    for cell in doc['cells']:
        cell['agent'].append('{study_spec}')
    write(grid[0], doc)
    model = sg.GridManifest.load(grid[0])
    approval = authority(tmp_path, monkeypatch, sg.override_context(model),
        {'/task/coordinate/0': {'values': [1.1], 'physics': False}})
    request = proposal(tmp_path, approval, {'/task/coordinate/0': 1.1})
    record = sg.record_override(*grid, 'cell-0', request)
    ledger = sg.submit(*grid)
    attempt = ledger['cells']['cell-0']['attempts'][0]
    assert attempt['override']['receipt_sha256'] == record['receipt_sha256']
    allocation_request = sg.read_json(Path(attempt['request_dir']) / 'request.json')
    effective = Path(allocation_request['agent']['argv'][-1])
    assert sg.read_json(effective)['task']['coordinate'][0] == 1.1
    assert sg.read_json(Path(doc['cells'][0]['study_spec']))['task']['coordinate'][0] == 1
    finish(grid, monkeypatch)
    harvest = sg.harvest(*grid)
    assert harvest.cells[0].overridden and harvest.cells[0].regime == 'integration-failure'
    assert harvest.cells[0].receipt_sha256 == record['receipt_sha256']
    # Supersession resumes the exact same settings and keeps the previous attempt.
    ledger = sg.submit(*grid, resume=True, supersede=['cell-0'])
    attempts = ledger['cells']['cell-0']['attempts']
    assert len(attempts) == 2 and attempts[0]['superseded']
    assert attempts[1]['override'] == record
    from ravel.plotting import parameter_plane as pp
    from ravel.plotting.reference_metrics import _Recorder
    sg.harvest(*grid)
    source = dict(study_grid=str(grid[1] / 'harvest.json'), scenario='baseline', x='u', y='v',
                  surfaces={'observed': 'quantity'}, shade=False)
    resolved, metadata = pp._grid_from_study_harvest(source, tmp_path, _Recorder())
    import numpy as np
    assert np.isnan(resolved['observed'][0, 0])
    assert metadata['overridden_cells'][0]['regime'] == 'integration-failure'
    spec = write(tmp_path / 'figure.json', dict(schema_version=1,
        axes={'x': {'label': 'First coordinate'}, 'y': {'label': 'Second coordinate'}}, panels=[{'grid': source}]))
    receipt = pp.run_spec(spec, tmp_path / 'figure')
    assert receipt['panels'][0]['grid_source']['overridden_cells'][0]['id'] == 'cell-0'


def test_override_fails_when_policy_context_or_evidence_changes(tmp_path, monkeypatch):
    directory, manifest = planned(tmp_path)
    approval = authority(tmp_path, monkeypatch, po.digest('unrelated-context'), {})
    request = proposal(tmp_path, approval)
    with pytest.raises(ValueError, match='different grid or scan'):
        scan.record_override(directory, manifest['points'][0]['tag'], request)
    Path(request['diagnostics'][0]['path']).write_text('changed')
    with pytest.raises(ValueError, match='evidence or settings changed'):
        scan.record_override(directory, manifest['points'][0]['tag'], request)


@pytest.mark.parametrize('changes', [{'/absent': 1}, {'/x': 1, '/x/a': 2}, {'/x/-1': 2}, {'/x': float('nan')}])
def test_field_replacements_refuse_undefined_overlap_negative_indices_and_nonfinite(changes):
    with pytest.raises(ValueError):
        po.replace_fields({'x': [1]}, changes)


def test_toml_round_trip_has_no_dependency():
    import tomllib
    settings = {'card': {'signed': [-1, 0, 1], 'flag': False, 'label': 'supplied', 'quoted.key': 1.2}}
    assert tomllib.loads(po.toml_text(settings)) == settings


def test_native_proposal_and_stage_identity_include_the_override_receipt(tmp_path, monkeypatch):
    from test_native_effective_config import slepton_configuration
    from ravel.physics import native_pipeline as native
    root = tmp_path / 'point'
    config = slepton_configuration(root, monkeypatch)
    import tomllib
    settings = tomllib.loads(config.read_text())
    approval = authority(tmp_path, monkeypatch, po.digest('supplied-context'),
        {'/madgraph/run/seed': {'values': [4], 'physics': False}})
    request = proposal(tmp_path, approval, {'/madgraph/run/seed': 4})
    point = {'parameters': {'coordinate': 1}}
    record, effective = po.admit('point-a', request, settings, point=point,
        population={'point-a': point}, axes=[{'name': 'coordinate', 'values': [1]}],
        successful=lambda p: [], context_sha256=po.digest('supplied-context'))
    changed = root / 'changed.toml'
    changed.write_text(po.toml_text(effective))
    receipt = write(root / 'inputs/active-point-override.json', record)
    plan = native.build_execution_plan(root, changed)
    assert plan['point_override'] == record
    assert po.pin(receipt) in [{'path': p['path'], 'sha256': p['sha256']} for p in plan['sources']]
    assert all(str(receipt) in stage['inputs'] for stage in plan['stages'])
    native.write_plan(plan)
    native.prepare(plan)
    assert not (root / 'output').exists()
    assert str(native.output_root(plan)) in (native.output_root(plan) / 'run.mg5').read_text()
    assert native.load_plan(plan['plan_path'])['point_override'] == record
    receipt.write_text('{}')
    with pytest.raises(ValueError, match='input changed'):
        native.load_plan(plan['plan_path'])


def test_csv_holes_and_an_entirely_missing_scan_stay_explicit(tmp_path):
    import csv
    directory, manifest = planned(tmp_path)
    manifest['output'] = {'format': 'csv', 'path': 'result.csv'}
    write(directory / 'scan_manifest.json', manifest)
    scan.cmd_assemble(SimpleNamespace(scandir=str(directory), out=None))
    with (directory / 'result.csv').open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2 and all(r['status'] == 'missing' and r['response'] == '' for r in rows)
    assert all(r['regime'] == 'default' for r in rows)


def test_scope_is_supported_by_real_contract_and_study_validators(tmp_path):
    from test_validate_task_contract import contract as task_contract
    from ravel.validation import validate_task_contract as validator
    from test_science_workflow import fixture
    from ravel.workflow import science
    scope = {'context_sha256': po.digest('scope'), 'fields': {
        '/settings/accuracy': {'values': [.01], 'physics': False}}}
    contract = task_contract(point_override_scope=scope)
    assert not validator.validate(contract)
    contract['point_override_scope']['fields']['/settings/accuracy']['physics'] = 'false'
    assert validator.validate(contract)
    scope['fields']['/settings/accuracy']['physics'] = False
    _, path = fixture(tmp_path)
    spec = sg.read_json(path)
    spec['point_override_scope'] = scope
    assert science.validate(spec) is None
    spec['point_override_scope'] = {'fields': {}}
    with pytest.raises(ValueError):
        science.validate(spec)


def test_native_override_command_records_the_effective_identity(tmp_path, monkeypatch, capsys):
    directory, manifest = planned(tmp_path)
    approval = authority(tmp_path, monkeypatch, scan.override_context(manifest),
        {'/parameters/accuracy': {'values': [.01], 'physics': False}})
    request = write(tmp_path / 'override.json', proposal(tmp_path, approval))
    import sys
    monkeypatch.setattr(sys, 'argv', ['scan', 'override', str(directory),
        '--point', manifest['points'][0]['tag'], '--record', str(request)])
    scan.main()
    assert 'receipt_sha256' in capsys.readouterr().out


def test_grid_override_command_and_physics_comparison_gate(grid, tmp_path, monkeypatch, capsys):
    from ravel import cli
    doc = sg.read_json(grid[0])
    doc['cells'][0]['agent'].append('{study_spec}')
    write(grid[0], doc)
    model = sg.GridManifest.load(grid[0])
    approval = authority(tmp_path, monkeypatch, sg.override_context(model),
        {'/task/coordinate/0': {'values': [1.1], 'physics': True}})
    request = write(tmp_path / 'override.json', proposal(tmp_path, approval, {'/task/coordinate/0': 1.1}))
    assert cli.main(['study-grid', 'override', '--manifest', str(grid[0]), '--grid-dir', str(grid[1]),
        '--cell', 'cell-0', '--record', str(request)]) == 2
    assert 'neighbour comparison' in capsys.readouterr().err


def test_override_scope_uses_a_real_recorded_parent_approval(tmp_path):
    from test_checkin2_gate import _run, _ws
    directory, manifest = planned(tmp_path / 'scan')
    parent = _run(tmp_path / 'parent', plan='smoke', checkin2=False)
    contract_path = parent / 'inputs/task_contract.json'
    contract_doc = sg.read_json(contract_path)
    contract_doc['point_override_scope'] = {'context_sha256': scan.override_context(manifest),
        'fields': {'/parameters/accuracy': {'values': [.01], 'physics': False}}}
    write(contract_path, contract_doc)
    done = _ws('approve', '--rundir', parent, '--quote', 'Approve the supplied repair scope', '--plan', 'smoke')
    assert done.returncode == 0, done.stderr
    _, files = al._approval(parent, 'checkin1', 'smoke')
    approval = dict(rundir=str(parent), route='checkin1', rung='smoke', approval_files=files)
    record = scan.record_override(directory, manifest['points'][0]['tag'], proposal(tmp_path, approval))
    assert record['authority'] == 'delegated'


def test_native_plot_marks_overrides_and_does_not_bridge_declared_holes(tmp_path):
    from test_declarative_scan_plots import contract as plot_contract
    from ravel.plotting import scan_contour as renderer
    data, spec = plot_contract(tmp_path, size=3)
    removed = data['points'].pop(4)
    data['point_population'] = [{'tag': p['tag'], 'parameters': {k: p[k] for k in ('alpha', 'beta')},
        'status': 'completed'} for p in data['points']]
    data['point_population'].append({'tag': removed['tag'], 'parameters': {'alpha': 1, 'beta': 1},
        'status': 'missing', 'overridden': True, 'regime': 'threshold', 'receipt_sha256': 'supplied'})
    report = renderer.render_spec(data, spec, write=False)
    assert report['overridden_points'][0]['tag'] == removed['tag']
    assert report['layers'][1]['masked_triangles'] > 0


def test_populations_cannot_silently_drop_points(grid, tmp_path):
    directory, manifest = planned(tmp_path / 'scan')
    manifest['points'].pop()
    write(directory / 'scan_manifest.json', manifest)
    with pytest.raises(ValueError, match='population changed'):
        scan.load_manifest(str(directory))
    sg.submit(*grid)
    ledger = sg.read_json(grid[1] / sg.LEDGER)
    del ledger['cells']['cell-0']
    write(grid[1] / sg.LEDGER, ledger)
    with pytest.raises(ValueError, match='population changed'):
        sg.status(*grid)


def test_grid_rejects_stale_output_even_when_the_allocation_completed(grid, tmp_path, monkeypatch):
    doc = sg.read_json(grid[0])
    doc['cells'][0]['agent'].append('{study_spec}')
    write(grid[0], doc)
    approval = authority(tmp_path, monkeypatch, sg.override_context(sg.GridManifest.load(grid[0])),
        {'/task/coordinate/0': {'values': [1.1], 'physics': False}})
    sg.record_override(*grid, 'cell-0', proposal(tmp_path, approval, {'/task/coordinate/0': 1.1}))
    sg.submit(*grid)
    finish(grid, monkeypatch)
    harvest = sg.harvest(*grid)
    assert harvest.cells[0].status == 'completed'
    source = Path(harvest.cells[0].artifacts['quantity'].path)
    write(source, {'value': 99})
    stale = sg.harvest(*grid).cells[0]
    assert stale.status == 'missing' and not stale.values and 'receipt' in stale.detail


def test_native_line_with_a_hole_renders_a_gap_and_marks_the_override(tmp_path):
    from test_declarative_scan_plots import contract as plot_contract, selected_spec
    from ravel.plotting import scan_contour as renderer
    data, _ = plot_contract(tmp_path)
    data['points'] = [{'tag': f'p{i}', 'dm': float(i), 'mu95_obs': 1.0 + i, 'mu95_exp': 1.5 + i,
                       'mu95_exp_band': [.5 + i, 1 + i, 1.5 + i, 2 + i, 2.5 + i]}
                      for i in (0, 1, 3)]
    data['n_planned'] = 4
    data['point_population'] = [{'tag': p['tag'], 'parameters': {'dm': p['dm']}, 'status': 'completed'}
                                for p in data['points']]
    data['point_population'].append({'tag': 'p2', 'parameters': {'dm': 2.0}, 'status': 'missing',
        'overridden': True, 'regime': 'width', 'receipt_sha256': 'supplied'})
    spec = selected_spec(data, tmp_path / 'line', 'line')
    report = renderer.render_spec(data, spec, write=False)
    assert report['overridden_points'] == [{'tag': 'p2', 'regime': 'width', 'receipt_sha256': 'supplied'}]
    assert report['missing_scan_points'] == 1


def test_older_scan_manifests_refuse_overrides_clearly(tmp_path):
    directory, manifest = planned(tmp_path)
    manifest.pop('schema_version'); manifest.pop('axes')
    write(directory / 'scan_manifest.json', manifest)
    with pytest.raises(ValueError, match='current declarative scan manifest'):
        scan.record_override(directory, manifest['points'][0]['tag'], {})


@pytest.mark.parametrize('damage', ['missing', 'changed', 'unlisted', 'old-manifest', 'old-receipt'])
def test_native_quantity_manifest_refuses_stale_files_as_failed_cells(tmp_path, monkeypatch, damage):
    directory, manifest = planned(tmp_path)
    approval = authority(tmp_path, monkeypatch, scan.override_context(manifest),
        {'/parameters/accuracy': {'values': [.01], 'physics': False}})
    original = manifest['points'][0]
    record = scan.record_override(directory, original['tag'], proposal(tmp_path, approval))
    _, manifest = scan.load_manifest(str(directory))
    point = manifest['points'][0]
    out = Path(point['run_dir']) / point['output_directory']
    result = write(out / 'response.json', {'value': 7})
    report = {'point_receipt_sha256': record['receipt_sha256'], 'quantity_outputs': [po.pin(result)]}
    write(out / 'native_execution_result.json', report)
    assert scan.harvest_point(point)['response'] == 7
    if damage == 'missing':
        result.unlink()
    elif damage == 'changed':
        write(result, {'value': 99, 'point_receipt_sha256': record['receipt_sha256']})
    elif damage == 'unlisted':
        report['quantity_outputs'] = [po.pin(write(out / 'unrelated.json', {'value': 7}))]
    elif damage == 'old-manifest':
        report.pop('quantity_outputs')
    else:
        report['point_receipt_sha256'] = 'older'
    write(out / 'native_execution_result.json', report)
    scan.cmd_assemble(SimpleNamespace(scandir=str(directory), out=None))
    assembled = json.loads((directory / 'requested.json').read_text())
    assert assembled['point_population'][0]['status'] == 'failed'
    assert original['tag'] in assembled['invalid_points'] and assembled['points'] == []


@pytest.mark.parametrize('supervised', [False, True])
def test_native_default_and_override_outputs_remain_independently_harvestable(tmp_path, monkeypatch, supervised):
    from test_native_dispatch import configuration, stub_backend, approve_fixture, quick_supervisor
    from ravel.physics import native_pipeline as native
    directory, manifest = planned(tmp_path)
    point = manifest['points'][0]
    root = Path(point['run_dir'])
    if supervised:
        stub_backend(root, monkeypatch)
    config = configuration(root)
    if supervised:
        from model_validation_fixture import native_evidence
        native_evidence(config, native.native_build_root())
    (root / point['config']).write_bytes(config.read_bytes())
    point['quantities'] = [{'name': 'response', 'source': 'output/normalization.json', 'field': 'applied_cross_section_pb'}]
    manifest['quantities'] = point['quantities']
    write(directory / 'scan_manifest.json', manifest)

    def produce(identity, value):
        plan = native.build_execution_plan(root, identity['config'])
        if supervised:
            approve_fixture(plan)
            code = native.execute_plan(plan, supervisor=quick_supervisor)
            assert code == 0, {p.name: p.read_text()[-3000:] for p in native.log_root(plan).glob('*.log')}
            from ravel.workflow.execution import validate_execution
            assert validate_execution(root) == []
        else:
            native.write_plan(plan)
            native.prepare(plan)
            for path in plan['quantity_outputs']:
                write(Path(path), {'applied_cross_section_pb': value})
            assert native.main(['report', '--plan', plan['plan_path']]) == 0
        out = native.output_root(plan)
        report = json.loads((out / 'native_execution_result.json').read_text())
        assert {p['path']: p['sha256'] for p in report['quantity_outputs']} == {
            po.pin(path)['path']: po.pin(path)['sha256'] for path in plan['quantity_outputs']}
        assert all(Path(path).is_relative_to(out) for stage in plan['stages'] for path in stage['outputs'])
        return plan

    # Test artifact custody directly: inert native tools carry no delivery review.
    def harvest(identity):
        return scan.harvest_quantities(identity, root)

    default = produce(point, 1.6)
    frozen = {p: p.read_bytes() for p in (root / 'output').rglob('*') if p.is_file()}
    frozen[Path(default['plan_path'])] = Path(default['plan_path']).read_bytes()
    fields = {'/analysis/kfactor': {'values': [.9, 1.], 'physics': False}}
    if supervised:
        # Child processes verify this authority too, so use a real recorded fixture.
        from test_checkin2_gate import _run, _ws
        parent = _run(tmp_path / 'parent', plan='smoke', checkin2=False)
        parent_contract = sg.read_json(parent / 'inputs/task_contract.json')
        parent_contract['point_override_scope'] = {
            'context_sha256': scan.override_context(manifest), 'fields': fields}
        write(parent / 'inputs/task_contract.json', parent_contract)
        approved = _ws('approve', '--rundir', parent, '--quote', 'Approve the synthetic repair scope', '--plan', 'smoke')
        assert approved.returncode == 0, approved.stderr
        _, files = al._approval(parent, 'checkin1', 'smoke')
        approval = dict(rundir=str(parent), route='checkin1', rung='smoke', approval_files=files)
    else:
        approval = authority(tmp_path, monkeypatch, scan.override_context(manifest), fields)
    request = proposal(tmp_path, approval, {'/analysis/kfactor': .9})
    first_record = scan.record_override(directory, point['tag'], request)
    _, changed = scan.load_manifest(str(directory))
    current = changed['points'][0]
    # An incomplete new attempt cannot consume the completed default output.
    with pytest.raises(ValueError, match='receipt'):
        harvest(current)
    varied = produce(current, 1.8)
    assert varied['plan_path'] != default['plan_path']
    assert str(native.output_root(varied)) in (native.output_root(varied) / 'run.mg5').read_text()
    assert harvest(current)['response'] == 1.8
    assert len(current['attempt_history']) == 2
    for identity, value in zip(current['attempt_history'], (1.6, 1.8)):
        previous = {**point, **identity}
        assert harvest(previous)['response'] == value
    assert all(p.read_bytes() == contents for p, contents in frozen.items())
    # Another override keeps the first receipt and plan usable at their exact bytes.
    frozen_varied = Path(varied['plan_path']).read_bytes()
    scan.record_override(directory, point['tag'], proposal(tmp_path, approval, {'/analysis/kfactor': 1.}))
    _, latest = scan.load_manifest(str(directory))
    assert len(latest['points'][0]['attempt_history']) == 3
    assert current['override']['receipt_sha256'] == first_record['receipt_sha256']
    assert Path(varied['plan_path']).read_bytes() == frozen_varied
    assert native.load_plan(varied['plan_path']) == varied
    assert harvest(current)['response'] == 1.8


def test_native_quantity_replaced_during_hashing_cannot_escape_the_receipt(tmp_path, monkeypatch):
    from ravel.physics import native_normalization as normalization
    source = write(tmp_path / 'output/response.json', {'value': 7})
    write(source.parent / 'native_execution_result.json', {'quantity_outputs': [po.pin(source)]})
    point = {'parameters': {'coordinate': 1},
             'quantities': [{'name': 'response', 'source': 'output/response.json', 'field': 'value'}]}
    original = normalization.fingerprint
    replaced = False
    def replace_after_hash(path):
        nonlocal replaced
        identity = original(path)
        if Path(path) == source and not replaced:
            replaced = True
            write(source, {'value': 99})
        return identity
    monkeypatch.setattr(normalization, 'fingerprint', replace_after_hash)
    with pytest.raises(ValueError, match='changed during harvesting'):
        scan.harvest_quantities(point, tmp_path)



@pytest.mark.parametrize('directory', ['outside-logs', 'logs/state', 'logs/execution'])
def test_native_attempt_logs_keep_the_supervisor_path_restrictions(tmp_path, directory):
    from ravel.workflow.approval_inputs import _producers
    with pytest.raises(ValueError):
        _producers(tmp_path, [{'stage': 'generate', 'outputs': []}], True,
                   native_log_directory=directory)



def test_scan_launch_audit_uses_the_selected_attempt_plan(tmp_path, monkeypatch):
    from ravel.workflow import launch_authorization, workflow_state
    root = tmp_path / 'point'
    receipt = 'a' * 64
    relative = 'attempts/' + receipt + '/output'
    point = {'tag': 'point-a', 'run_dir': str(root), 'output_directory': relative,
             'override': {'receipt_sha256': receipt}}
    write(root / 'inputs/native_execution_plan.json', {'required_compute_plan': 'scan', 'plan_sha256': 'default'})
    write(root / Path(relative).parent / 'inputs/native_execution_plan.json',
          {'required_compute_plan': 'scan', 'plan_sha256': 'selected'})
    seen = []
    monkeypatch.setattr(workflow_state, 'verify_checkin2_go', lambda path: [])
    monkeypatch.setattr(launch_authorization, 'audit_launches',
                        lambda path, **kw: seen.append(kw['plan_sha256']) or [])
    assert launch_authorization.audit_scan_launches(tmp_path, {'points': [point]},
                                                   {'points': [{'tag': 'point-a'}]}) == []
    assert seen == ['selected']
