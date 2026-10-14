"""Synthetic complete SLHA algebra controls, no solver or physical fixture."""
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
import math
from pathlib import Path
import threading
import pytest

from ravel.physics import nmssm_yukawa_map as n
from ravel.workflow import science, agent_host, agent_graph, execution
from ravel.workflow.state_io import atomic_json, read_json


def pin(p):
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}


def fixture(tmp):
    tmp.mkdir(parents=True, exist_ok=True)
    original = b'BLOCK MODSEL\n 6 0\nBLOCK FlexibleSUSY\n 3 1\n 4 0\n 12 0\n 23 1\nBLOCK UNKNOWN\n arbitrary retained row\n'
    mixing = [['0.6', '0.8', '0'], ['-0.8', '0.6', '0'], ['0', '0', '1']]
    text = 'BLOCK SPINFO\n 3 retained artificial warning\nBLOCK MASS\n'
    text += ''.join(f' {pdg} {m}\n' for pdg, m in zip(n.HIGGS, (125, 300, 500)))
    for _, _, pdgs, _, _ in n.FAMILIES:
        text += ''.join(f' {pdg} {format(y*100/math.sqrt(2), ".17g")}\n'
                        for pdg, y in zip(pdgs, (.001, .01, .1)))
    text += 'BLOCK NMHMIX\n' + ''.join(f' {i+1} {j+1} {mixing[i][j]}\n' for i in range(3) for j in range(3))
    for _, block, _, _, _ in n.FAMILIES:
        text += f'BLOCK {block} Q= 1000\n' + ''.join(
            f' {i+1} {j+1} {(".001", ".01", ".1")[i] if i == j else "0"}\n'
            for i in range(3) for j in range(3))
    text += 'BLOCK HMIX Q= 1000\n 102 100\n 103 100\nDECAY 25 .004\n .25 2 22 22\nBLOCK IMNMNMIX\n 1 1 -.2\n'
    inp = tmp/'input.slha'; inp.write_bytes(original)
    spec = tmp/'spectrum.slha'; spec.write_text(text)
    doc = {'schema_version': 1, 'operation': 'nmssm_tree_yukawa', 'profile': n.named.NAME,
           'spectrum': pin(spec), 'input_card': pin(inp), 'scale_token': '1000',
           'validity': deepcopy(n.VALIDITY), 'checks': {'mixing_absolute': '0',
               'mass_squared_absolute_GeV2': '1e-12', 'mass_squared_relative': '1e-14'},
           'origin': {'kind': 'supplied_unqualified'}}
    path = tmp/'request.json'; atomic_json(path, doc)
    return {'request': str(path)}, doc


def resave(task, doc):
    for key in ('spectrum', 'input_card'):
        doc[key] = pin(Path(doc[key]['path']))
    atomic_json(Path(task['request']), doc)


def test_complete_81_couplings_sign_and_source_mass_separation(tmp_path):
    task, _ = fixture(tmp_path)
    r = n.compile_map(task, tmp_path)
    assert len(r['couplings_and_channels']) == 81
    assert sum(c['flavour_zero_derived'] for c in r['couplings_and_channels']) == 54
    assert len(r['mass_yukawa_checks']) == 9
    rows = {c['id']: c for c in r['couplings_and_channels']}
    assert F(rows['h25_d33']['exact_prefactor_over_sqrt2']) == F('-3/50')
    assert F(rows['h25_u33']['exact_prefactor_over_sqrt2']) == F('-2/25')
    assert F(rows['h35_d33']['exact_prefactor_over_sqrt2']) == F('2/25')
    assert rows['h45_d33']['HEPTAPOD_coordinates']['gL']['real'] == 0
    assert all(c['tree_reference']['partial_width_GeV'] == 0 for c in r['couplings_and_channels'] if c['flavour_zero_derived'])
    assert r['full_spectrum']['original_lines'][-1] == ' 1 1 -.2\n'
    assert r['full_spectrum']['sections'][-2]['width'] == '.004'
    assert n.verify_result(task, tmp_path, r)
    assert all(r[k] is False for k in ('physics_validated', 'rge_applied', 'eft_matching_applied', 'supplied_total_width_replaced'))


@pytest.mark.parametrize('family,code,color,column', [('d', 5, 3, .6), ('u', 6, 3, .8), ('e', 15, 1, .6)])
def test_selected_tree_width_matches_independent_scalar_formula(tmp_path, family, code, color, column):
    task, _ = fixture(tmp_path)
    r = n.compile_map(task, tmp_path)
    row = next(c for c in r['couplings_and_channels'] if c['id'] == 'h25_'+family+'33')
    g, m, f = -.1*column/math.sqrt(2), 125, .1*100/math.sqrt(2)
    expected = color*g*g*m/(8*math.pi)*(1-4*f*f/m/m)**1.5
    assert row['tree_reference']['partial_width_GeV'] == pytest.approx(expected, rel=2e-14)
    assert row['outgoing_pdgs'] == [-code, code]


def test_closed_threshold_retains_all_rows_without_offshell_zero(tmp_path):
    task, doc = fixture(tmp_path)
    p = Path(doc['spectrum']['path']); p.write_text(p.read_text().replace(' 25 125\n', ' 25 0.1\n'))
    resave(task, doc)
    rows = n.compile_map(task, tmp_path)['couplings_and_channels']
    assert len(rows) == 81
    assert all(c['tree_reference'] is None and c['channel_status'].startswith('closed') for c in rows if c['parent_pdg'] == 25)


@pytest.mark.parametrize('mutation', ['pole', 'no-sm', 'forced', 'no-bsm', 'FV', 'CPV', 'wrong-profile', 'wrong-scale',
    'extra-quantity', 'missing-Y', 'duplicate-Y', 'missing-mixing', 'offdiag', 'imaginary', 'nonorthogonal',
    'negative-mass', 'negative-Y', 'wrong-mass', 'native-error', 'mass-missing', 'duplicate-address', 'bool-band', 'negative-band'])
def test_incompatible_or_incomplete_populations_refuse(tmp_path, mutation):
    task, doc = fixture(tmp_path)
    p, ip = Path(doc['spectrum']['path']), Path(doc['input_card']['path'])
    text, inp = p.read_text(), ip.read_text()
    if mutation == 'pole': inp = inp.replace(' 4 0', ' 4 2')
    if mutation == 'no-sm': inp = inp.replace(' 3 1', ' 3 0')
    if mutation == 'forced': inp = inp.replace(' 12 0', ' 12 1')
    if mutation == 'no-bsm': inp = inp.replace(' 23 1', ' 23 0')
    if mutation == 'FV': inp = inp.replace(' 6 0', ' 6 1')
    if mutation == 'CPV': inp = inp.replace(' 6 0', ' 6 0\n 5 1')
    if mutation == 'wrong-profile': doc['profile'] = 'NMSSM-CPV'
    if mutation == 'wrong-scale': doc['scale_token'] = '2000'
    if mutation == 'extra-quantity': doc['validity']['eft_matching'] = True
    if mutation == 'missing-Y': text = text.replace('BLOCK YD Q= 1000', 'BLOCK OTHER Q= 1000')
    if mutation == 'duplicate-Y': text += 'BLOCK YD Q= 1000\n 1 1 .001\n'
    if mutation == 'missing-mixing': text = text.replace(' 1 2 0.8\n', '')
    if mutation == 'offdiag': text = text.replace('BLOCK YD Q= 1000\n 1 1 .001\n 1 2 0', 'BLOCK YD Q= 1000\n 1 1 .001\n 1 2 .01')
    if mutation == 'imaginary': text += 'BLOCK IMNMHMIX\n'+''.join(f' {i} {j} {".1" if i==j==1 else "0"}\n' for i in range(1,4) for j in range(1,4))
    if mutation == 'nonorthogonal': text = text.replace(' 1 1 0.6', ' 1 1 0.7')
    if mutation == 'negative-mass': text = text.replace(' 25 125', ' 25 -125')
    if mutation == 'negative-Y': text = text.replace(' 1 1 .001', ' 1 1 -.001')
    if mutation == 'wrong-mass': text = text.replace(' 25 125', ' 25 125') + 'BLOCK MASS\n 5 10\n'
    if mutation == 'native-error': text += 'BLOCK SPINFO\n 4 retained real native failure\n'
    if mutation == 'mass-missing': text = text.replace(' 45 500\n', '')
    if mutation == 'duplicate-address': text = text.replace(' 1 1 0.6\n', ' 1 1 0.6\n 1 1 0.6\n')
    if mutation == 'bool-band': doc['checks']['mixing_absolute'] = True
    if mutation == 'negative-band': doc['checks']['mass_squared_relative'] = '-1'
    p.write_text(text); ip.write_text(inp); resave(task, doc)
    with pytest.raises(ValueError): n.compile_map(task, tmp_path)


def specification(task):
    return {'schema_version': 2, 'mode': 'nmssm-yukawa-map', 'source': 'Explicit artificial complete tree SLHA source control',
        'assumptions': ['Artificial data, not a solved/validated physical spectrum. Declared tree-only convention.'],
        'max_seconds': 30, 'approval_mode': 'scripted_yes', 'task': task, 'max_attempts': 1,
        'review_policy': {'schema_version': 1, 'policy': {'schema_version': 1,
          'actors': {'proposer': 'p', 'executor': 'e', 'physics_critic': 'c', 'skeptical_verifier': 'v', 'physics_decider': 'd'},
          'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
          'required_checks': [{'id': 'integrity', 'kind': 'integrity'}, {'id': 'physical', 'kind': 'scientific'}],
          'claim_scopes': {n.SCOPE: {'checks': ['integrity'], 'actions': ['delivery']}}},
          'correction_contract': {'task_fields': [], 'input_slots': []}}}


def test_actual_ordinary_plan_input_closure_without_approval(tmp_path):
    task, _ = fixture(tmp_path)
    spec = specification(task); path = tmp_path/'science.json'; atomic_json(path, spec)
    plan = science.plan(tmp_path/'run', path)
    assert science.adapter(spec) is n and science._new_capability(spec)
    assert set(n.inputs(task, tmp_path)) <= set(science.task_inputs(spec, tmp_path))
    assert not (tmp_path/'run/inputs/science-approval.json').exists()
    spec['review_policy']['policy']['claim_scopes'][n.SCOPE]['actions'] += ['reuse']
    atomic_json(path, spec)
    with pytest.raises(ValueError, match='delivery-only'): science.plan(tmp_path/'bad', path)


def test_actual_common_worker_with_explicit_synthetic_admission(tmp_path, monkeypatch):
    from ravel.physics import science_worker
    task, _ = fixture(tmp_path)
    spec = specification(task); rd = tmp_path/'run'; (rd/'inputs').mkdir(parents=True)
    plan = {'schema_version': 2, 'base_dir': str(tmp_path), 'attempt': 1,
            'output_directory': 'outputs/attempt-1', 'max_seconds': 30, 'stage_binding': {'input_snapshot': {}}}
    atomic_json(rd/'inputs/science-plan.json', plan); atomic_json(rd/'inputs/science.json', spec)
    for module in (science, science_worker):
        monkeypatch.setattr(module, 'verify_worker', lambda _: plan)
        monkeypatch.setattr(module, 'execution_spec', lambda _: spec)
    assert science_worker.main([str(rd)]) == 0
    result = read_json(rd/'outputs/attempt-1/result.json')
    assert result['status_scope'] == n.SCOPE and result['population']['channels'] == 81
    assert read_json(rd/'outputs/attempt-1/verification.json')['physics_validated'] is False
    result['branching_ratios_predicted'] = True
    with pytest.raises(ValueError): science_worker.diagnostic_presentation(spec['mode'], result)


class Control:
    def __init__(self): self.calls = []; self.cancel = threading.Event()
    def cancelled(self): return False
    def call(self, label, kind, req, fn, output_tokens=0):
        self.calls.append((label, kind)); return fn()


def graph_fixture(tmp):
    task, _ = fixture(tmp)
    pins = [{'id': str(i), 'path': str(p), 'sha256': execution.file_hash(p)} for i, p in enumerate(n.inputs(task, tmp))]
    reqid = next(p['id'] for p in pins if p['path'] == task['request'])
    node = {'id': 'conventions', 'kind': 'tool', 'role': 'designer', 'depends_on': [], 'inputs': pins,
        'packet': None, 'action': 'nmssm-yukawa-context', 'parameters': {'request_input': reqid}, 'max_attempts': 1}
    request = {'schema_version': 1, 'graph_id': 'g', 'graph_revision': 'a'*64, 'node_id': node['id'],
        'generation': 1, 'node_sha256': execution.digest(node), 'request_id': 'b'*64,
        'input_artifacts': deepcopy(pins), 'packet': None, 'dependencies': []}
    return node, request


def test_actual_host_charged_context_and_exact_source_identities(tmp_path):
    node, request = graph_fixture(tmp_path)
    host = agent_host.AgentHost(); control = Control()
    result = host.execute(node, request, control)
    assert control.calls == [('nmssm-yukawa-context', 'tool')]
    assert result['value']['mode'] == 'nmssm-yukawa-map'
    assert result['value']['request']['validity'] == n.VALIDITY
    assert result['value']['execution_authorized'] is False
    identities = host.identity['sources']
    assert identities[n.__name__] == execution.file_hash(n.__file__)
    assert identities[n.ufo_decay.__name__] == execution.file_hash(n.ufo_decay.__file__)
    assert identities['nmssm.tree-map-equation-contract'] == execution.file_hash(n.API)


def test_actual_graph_context_counts_one_tool_call_and_reuses_current_receipt(tmp_path):
    node, _ = graph_fixture(tmp_path/'inputs')
    graph = {'schema_version': 1, 'graph_id': 'nmssm-source-context', 'nodes': [node],
             'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 1,
                        'max_wall_seconds': 20, 'max_reworks': 0}}
    root = tmp_path/'graph'
    agent_graph.create(root, graph)
    host = agent_host.AgentHost()
    status = agent_graph.execute(root, host, workers=1)
    assert status['complete'] and status['usage']['calls'] == 1
    assert not status['execution_authorized']
    assert agent_graph.execute(root, host, workers=1)['usage']['calls'] == 1


def test_host_missing_scientific_input_or_blind_role_refuses(tmp_path):
    node, request = graph_fixture(tmp_path)
    request['input_artifacts'] = request['input_artifacts'][:-1]
    with pytest.raises(agent_host.HostFailure): agent_host.AgentHost().execute(node, request, Control())
    node['role'] = 'critic'; request['input_artifacts'] = deepcopy(node['inputs'])
    with pytest.raises(agent_host.HostFailure): agent_host.AgentHost().execute(node, request, Control())


@pytest.mark.parametrize('mutation', ['coupling', 'width', 'missing-row', 'source', 'authority'])
def test_self_rehashed_result_edits_do_not_replace_derivation(tmp_path, mutation):
    task, _ = fixture(tmp_path); result = n.compile_map(task, tmp_path)
    if mutation == 'coupling': result['couplings_and_channels'][0]['HEPTAPOD_coordinates']['gL']['real'] = 99
    if mutation == 'width': result['couplings_and_channels'][0]['tree_reference']['partial_width_GeV'] = 99
    if mutation == 'missing-row': result['couplings_and_channels'].pop()
    if mutation == 'source': result['scale_token_GeV'] = '2000'
    if mutation == 'authority': result['physics_validated'] = True
    with pytest.raises(ValueError, match='current released derivation'): n.verify_result(task, tmp_path, result)


def test_original_source_changed_during_derive_refuses(tmp_path, monkeypatch):
    task, doc = fixture(tmp_path); real = n.derive
    def changed(*args):
        r = real(*args)
        with Path(doc['spectrum']['path']).open('a') as stream: stream.write('# late mutation\n')
        return r
    monkeypatch.setattr(n, 'derive', changed)
    with pytest.raises(ValueError): n.run(task, tmp_path, tmp_path/'output')
    assert not (tmp_path/'output/nmssm-yukawa-map.json').exists()


def test_generated_output_changed_at_write_commitment_refuses(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path); real = n.named.write_exact
    def changed(path, obj):
        capture = real(path, obj)
        changed_obj = deepcopy(obj); changed_obj['physics_validated'] = True; atomic_json(path, changed_obj)
        return capture
    monkeypatch.setattr(n.named, 'write_exact', changed)
    with pytest.raises(ValueError, match='generated map output'): n.run(task, tmp_path, tmp_path/'output')
    assert (tmp_path/'output/failed-nmssm-yukawa-map.json').exists()


def test_accepted_origin_cannot_be_declared_without_real_gates(tmp_path):
    task, doc = fixture(tmp_path); doc['origin'] = {'kind': 'accepted_named_spectrum', 'run': str(tmp_path)}
    resave(task, doc)
    with pytest.raises((ValueError, OSError)): n.inputs(task, tmp_path)


@pytest.mark.parametrize('mutation', [None, 'raw-result', 'old-profile', 'other-input', 'different-return'])
def test_accepted_origin_real_reader_join_with_explicit_synthetic_review_gate(tmp_path, monkeypatch, mutation):
    from ravel.workflow import task_completion
    from ravel.physics import generated_spectrum
    task, doc = fixture(tmp_path)
    rd = tmp_path/'accepted'; out = rd/'outputs/attempt-1'; out.mkdir(parents=True)
    returned = out/'NMSSM.slha'; returned.write_bytes(Path(doc['spectrum']['path']).read_bytes())
    doc['spectrum'] = pin(returned); doc['origin'] = {'kind': 'accepted_named_spectrum', 'run': str(rd)}
    configpath = rd/'config.json'; configpath.write_text('{}')
    config = {'schema_version': 2, 'profile': n.named.NAME, 'input_card': doc['input_card']}
    result = {'status': 'passed', 'model_profile': n.named.NAME,
        'configuration': pin(configpath), 'generated_slha': {**pin(returned), 'bytes': returned.stat().st_size},
        'full_slha': n.named.inventory(returned.read_bytes()),
        'input_witness': {'all_input': n.named.inventory(Path(doc['input_card']['path']).read_bytes())}}
    if mutation == 'raw-result': result['full_slha']['raw_sha256'] = 'a'*64
    if mutation == 'old-profile': config['schema_version'] = 1
    if mutation == 'other-input': config['input_card'] = pin(returned)
    if mutation == 'different-return': doc['spectrum'] = pin(Path(tmp_path/'spectrum.slha'))
    atomic_json(out/'generated-spectrum.json', result); resave(task, doc)
    # This is a fabricated gate, not an accepted physical spectrum or review.
    monkeypatch.setattr(task_completion, '_accepted_review', lambda *args: (rd, {}))
    monkeypatch.setattr(science, 'execution_spec', lambda *args: {'mode': 'generated-spectrum', 'task': {}})
    monkeypatch.setattr(execution, 'load_execution', lambda *args: {'stages': {'science': {'outputs': [str(out)]}}})
    monkeypatch.setattr(generated_spectrum, '_load', lambda *args: (configpath, config))
    if mutation is None:
        r = n.compile_map(task, tmp_path)
        assert r['source_origin']['kind'] == 'accepted_named_spectrum'
        assert not r['physics_validated']
    else:
        with pytest.raises(ValueError): n.compile_map(task, tmp_path)


def test_duplicate_json_and_symlink_source_refuse(tmp_path):
    task, doc = fixture(tmp_path)
    path = Path(task['request']); path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError): n.load(task, tmp_path)
    atomic_json(path, doc); target = tmp_path/'alias.slha'; target.symlink_to(doc['spectrum']['path'])
    doc['spectrum']['path'] = str(target); atomic_json(path, doc)
    with pytest.raises(ValueError): n.inputs(task, tmp_path)


def test_public_cli_context_never_maps_or_executes(tmp_path, capsys):
    from ravel import cli
    task, _ = fixture(tmp_path)
    assert cli.main(['model-conventions', '--request', task['request']]) == 0
    context = json.loads(capsys.readouterr().out)
    assert context['ordinary_task'] == task and context['execution_authorized'] is False
    assert 'couplings_and_channels' not in context


def test_unique_wrong_mass_is_not_hidden_by_unmodified_yukawa(tmp_path):
    task, doc = fixture(tmp_path)
    p = Path(doc['spectrum']['path'])
    lines = p.read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if line.split() and line.split()[0] == '5')
    lines[index] = ' 5 10'
    p.write_text('\n'.join(lines)+'\n'); resave(task, doc)
    with pytest.raises(ValueError, match='mass/Yukawa'): n.compile_map(task, tmp_path)


def test_requested_scale_dialect_is_not_silently_relabelled(tmp_path):
    task, doc = fixture(tmp_path); doc['scale_token'] = '1e3'; resave(task, doc)
    with pytest.raises(ValueError): n.compile_map(task, tmp_path)


def test_duplicate_cp_selection_refuses_even_when_values_match(tmp_path):
    task, doc = fixture(tmp_path)
    p = Path(doc['input_card']['path']); p.write_text(p.read_text().replace(' 6 0', ' 6 0\n 5 0\n 5 0'))
    resave(task, doc)
    with pytest.raises(ValueError): n.compile_map(task, tmp_path)


@pytest.mark.parametrize('parameter', ['parent', 'yukawa'])
def test_nonfinite_or_unrepresentable_derived_width_does_not_pass(tmp_path, parameter):
    task, doc = fixture(tmp_path); p = Path(doc['spectrum']['path']); text = p.read_text()
    if parameter == 'parent': text = text.replace(' 25 125', ' 25 1e100')
    else:
        text = text.replace(' 3 3 .1', ' 3 3 1e-300')
    p.write_text(text); resave(task, doc)
    with pytest.raises(ValueError): n.compile_map(task, tmp_path)


def test_no_accepted_output_may_be_invented_from_context_only(tmp_path):
    task, _ = fixture(tmp_path)
    context = n.context(task, tmp_path)
    assert 'couplings_and_channels' not in context and context['execution_authorized'] is False
    assert context['request']['origin']['kind'] == 'supplied_unqualified'


def test_original_cards_remain_byte_identical_after_delivery(tmp_path):
    task, doc = fixture(tmp_path)
    before = {p: Path(p).read_bytes() for p in (doc['spectrum']['path'], doc['input_card']['path'])}
    result = n.run(task, tmp_path, tmp_path/'output')
    assert before == {p: Path(p).read_bytes() for p in before}
    assert result == read_json(tmp_path/'output/nmssm-yukawa-map.json')
    assert not result['supplied_card_changed'] and not result['branching_ratios_predicted']


def test_exact_released_primary_equation_and_writer_path():
    import zipfile
    root = Path(__file__).parents[1]/'fixtures/nmssm-yukawa/primary-source.zip'
    profile = n.named.profile()
    with zipfile.ZipFile(root) as z:
        for row in n._sources()['source_files']:
            rel = row['path'].removeprefix('nmssm/')
            assert hashlib.sha256(z.read(rel)).hexdigest() == row['sha256'] == profile['files'][row['path']]
        assert not any(name.startswith('SARAH-NMSSM/') for name in z.namelist())
        generated = z.read('models/NMSSM/NMSSM_mass_eigenstates.cpp').decode()
        slha = z.read('models/NMSSM/NMSSM_model_slha.cpp').decode()
        io = z.read('models/NMSSM/NMSSM_slha_io.cpp').decode()
        assert 'PHYSICAL(ZH) = ZH;' in generated
        assert 'if (pole_mass_loop_order == 0)\n      copy_DRbar_masses_to_pole_masses();' in generated
        assert 'slha_io.set_block("NMHMIX", LOCALPHYSICAL(ZH), "ZH");' in io
        for symbol, left, right, component in (('Yd', 'ZDL', 'ZDR', 0), ('Yu', 'ZUL', 'ZUR', 1), ('Ye', 'ZEL', 'ZER', 0)):
            assert f'fs_svd(MODELPARAMETER({symbol}), {symbol}_slha, {right}_slha, {left}_slha);' in slha
            assert f'slha_io.set_block("{symbol}", ToMatrix(MODELPARAMETER({symbol}_slha)), "{symbol}", model.get_scale());' in io
        assert 'm == u.transpose() * sigma * v' in z.read('src/linalg2.hpp').decode()
        assert 'for (int i = 1; i <= rows; ++i)' in z.read('src/slha_io.cpp').decode()


def test_source_svd_contraction_proves_full_offdiagonal_zero_with_nontrivial_rotations():
    # Exact real matrices independently contract the released SUM(j2,SUM(j1))
    # formula after Y = ZR^T * diag(y) * ZL. No C++/Eigen execution.
    R = [[F(3,5),F(4,5),F(0)],[-F(4,5),F(3,5),F(0)],[F(0),F(0),F(1)]]
    L = [[F(1),F(0),F(0)],[F(0),F(5,13),F(12,13)],[F(0),-F(12,13),F(5,13)]]
    diagonal = [F(1,1000),F(1,100),F(1,10)]
    Y = [[sum(R[a][j]*diagonal[a]*L[a][k] for a in range(3)) for k in range(3)] for j in range(3)]
    for outgoing in range(3):
        for incoming in range(3):
            contraction = sum(L[incoming][j2]*sum(R[outgoing][j1]*Y[j1][j2] for j1 in range(3)) for j2 in range(3))
            assert contraction == (diagonal[outgoing] if outgoing == incoming else 0)


@pytest.mark.parametrize('method', ['context', 'compile_map', 'run'])
def test_request_cannot_rebind_after_its_buffer_was_parsed(tmp_path, monkeypatch, method):
    task, doc = fixture(tmp_path); real = n._input_paths
    def changed(path, captured_doc):
        amended = deepcopy(doc); amended['checks']['mixing_absolute'] = '.1'
        atomic_json(path, amended)
        return real(path, captured_doc)
    monkeypatch.setattr(n, '_input_paths', changed)
    fn = getattr(n, method)
    with pytest.raises(ValueError, match='initial request changed'):
        fn(task, tmp_path, tmp_path/'output') if method == 'run' else fn(task, tmp_path)
    assert not (tmp_path/'output').exists()


@pytest.mark.parametrize('field', ['physics_validated', 'branching_ratios_predicted', 'coupling'])
def test_writer_cannot_mutate_detached_commitment_after_persistence(tmp_path, monkeypatch, field):
    task, _ = fixture(tmp_path); real = n.named.write_exact
    def writer(path, obj):
        committed = real(path, obj)
        if field == 'coupling': obj['couplings_and_channels'][0]['HEPTAPOD_coordinates']['gL']['real'] = 99
        else: obj[field] = True
        return committed
    monkeypatch.setattr(n.named, 'write_exact', writer)
    with pytest.raises(ValueError, match='initial commitment'):
        n.run(task, tmp_path, tmp_path/'output')
    assert not (tmp_path/'output/nmssm-yukawa-map.json').exists()
    failed = json.loads((tmp_path/'output/failed-nmssm-yukawa-map.json').read_text())
    assert failed['physics_validated'] is False and failed['branching_ratios_predicted'] is False
    assert failed['couplings_and_channels'][0]['HEPTAPOD_coordinates']['gL']['real'] != 99


def test_indirect_alias_to_returned_result_cannot_change_after_commit(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path); derive, writer = n._derive_captured, n.named.write_exact
    holder = {}
    def capture(*args):
        value = derive(*args); holder['initial'] = value; return value
    def mutate_original(path, obj):
        assert obj is not holder['initial']
        assert obj['couplings_and_channels'] is not holder['initial']['couplings_and_channels']
        committed = writer(path, obj)
        holder['initial']['couplings_and_channels'][0]['HEPTAPOD_coordinates']['gR']['real'] = 123
        return committed
    monkeypatch.setattr(n, '_derive_captured', capture)
    monkeypatch.setattr(n.named, 'write_exact', mutate_original)
    with pytest.raises(ValueError, match='initial commitment'):
        n.run(task, tmp_path, tmp_path/'output')


@pytest.mark.parametrize('mutation', ['forged-pin', 'self-rehashed-output'])
def test_writer_cannot_substitute_commitment_with_new_pin(tmp_path, monkeypatch, mutation):
    task, _ = fixture(tmp_path); writer = n.named.write_exact
    def substitute(path, obj):
        committed = writer(path, obj)
        if mutation == 'forged-pin': return {**committed, 'sha256': '0'*64}
        other = deepcopy(obj); other['physics_validated'] = True
        return writer(path, other)
    monkeypatch.setattr(n.named, 'write_exact', substitute)
    with pytest.raises(ValueError, match='initial commitment'):
        n.run(task, tmp_path, tmp_path/'output')


def test_writer_gets_detached_value_and_legitimate_return_matches_durable_json(tmp_path, monkeypatch):
    task, _ = fixture(tmp_path); derive, writer = n._derive_captured, n.named.write_exact
    holder = {}
    def capture(*args):
        value = derive(*args); holder['initial'] = value; return value
    def checked_writer(path, obj):
        assert obj is not holder['initial'] and obj == holder['initial']
        assert obj['full_spectrum'] is not holder['initial']['full_spectrum']
        return writer(path, obj)
    monkeypatch.setattr(n, '_derive_captured', capture)
    monkeypatch.setattr(n.named, 'write_exact', checked_writer)
    result = n.run(task, tmp_path, tmp_path/'output')
    assert result == holder['initial'] == json.loads((tmp_path/'output/nmssm-yukawa-map.json').read_text())
    assert result['physics_validated'] is False and result['branching_ratios_predicted'] is False
