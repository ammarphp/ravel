"""Portable source admission and actual public planning; never imports ROOT."""
import copy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ravel.physics import hs3_likelihood as h
from ravel.physics import hs3_native as n


@pytest.fixture
def graph():
    return {'metadata': {'hs3_version': '0.2', 'packages': [{'name': 'ROOT', 'version': '6.35.01'}]},
      'distributions': [{'name': 'model', 'type': 'histfactory_dist',
        'axes': [{'name': 'x', 'edges': [0, 1, 2]}], 'samples': [
          {'name': 'signal', 'data': {'contents': [2, 3]}, 'modifiers': [{'name': 'mu', 'parameter': 'mu', 'type': 'normfactor'}]},
          {'name': 'background', 'data': {'contents': [10, 20]}, 'modifiers': []}]}],
      'data': [{'name': 'obsData', 'type': 'binned', 'axes': [{'name': 'x', 'edges': [0, 1, 2]}], 'contents': [12, 23]}],
      'domains': [{'name': 'default_domain', 'type': 'product_domain', 'axes': [{'name': 'mu', 'min': 0, 'max': 10}]},
                  {'name': 'poi_domain', 'type': 'product_domain', 'axes': [{'name': 'mu', 'min': 0, 'max': 10}]}],
      'parameter_points': [{'name': 'default_values', 'parameters': [{'name': 'mu', 'value': 1}]}],
      'likelihoods': [{'name': 'likelihood', 'distributions': ['model'], 'data': ['obsData']}],
      'analyses': [{'name': 'analysis', 'likelihood': 'likelihood', 'domains': ['poi_domain'], 'parameters_of_interest': ['mu']}],
      'misc': {'ROOT_internal': {'ModelConfigs': {'analysis': {'mcName': 'ModelConfig', 'pdfName': 'model'}}}}}


def inspect(d):
    return h.inspect_graph(json.dumps(d).encode(), ['histfactory_dist', 'gaussian_dist', 'sum'])


def test_full_graph_retained_and_selected(graph):
    raw = json.dumps(graph, indent=3).encode()
    g = h.inspect_graph(raw, ['histfactory_dist'])
    assert g['document'] == graph
    assert g['inventory']['sha256'] == hashlib.sha256(raw).hexdigest()
    assert g['bindings']['analysis']['dataset'] == 'obsData'
    assert g['inventory']['datasets']['obsData'] == {'axes': ['x'], 'bins': 2, 'sum_weights': 35}


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a": NaN}', b'{"a": Infinity}', b''])
def test_strict_json(raw):
    with pytest.raises(ValueError):
        h.document(raw)


@pytest.mark.parametrize('change', [
    lambda g: g['metadata'].update(hs3_version='0.3'),
    lambda g: g['distributions'][0].update(type='unregistered_shape_dist'),
    lambda g: g['data'][0].update(type='unbinned'),
    lambda g: g['domains'][0].update(type='ellipse'),
    lambda g: g['data'][0].update(contents=[1]),
    lambda g: g['data'][0].update(contents=[1, -1]),
    lambda g: g['data'][0]['axes'][0].update(edges=[0, 1, 1]),
    lambda g: g['distributions'][0]['samples'][0]['modifiers'][0].update(type='made_up'),
    lambda g: g['distributions'][0]['samples'][0]['modifiers'][0].update(constraint_name='missing'),
    lambda g: g['analyses'][0].update(likelihood='missing'),
    lambda g: g['analyses'][0].update(parameters_of_interest=['missing']),
    lambda g: g['likelihoods'][0].update(data=['missing']),
    lambda g: g['parameter_points'][0]['parameters'][0].update(value=11),
    lambda g: g['parameter_points'][0]['parameters'][0].update(const='true'),
    lambda g: g['analyses'].append(copy.deepcopy(g['analyses'][0])),
])
def test_complete_source_refusals(graph, change):
    change(graph)
    with pytest.raises(ValueError):
        inspect(graph)


def selection(**extra):
    return {'analysis': 'analysis', 'parameter_point': 'default_values', 'points': [{'id': 'nominal', 'parameters': {}}, {'id': 'mu2', 'parameters': {'mu': 2}}], **extra}


def test_independent_points_and_constant_refusal(graph):
    g = inspect(graph); points = h.evaluation_points(g, selection())
    assert points[0]['values']['mu'] == 1
    assert points[1]['values']['mu'] == 2
    assert g['points']['default_values']['mu']['value'] == 1
    graph['parameter_points'][0]['parameters'][0]['const'] = True
    with pytest.raises(ValueError, match='nonconstant'):
        h.evaluation_points(inspect(graph), selection())


def test_selected_source_snapshot_missing_const_means_false(graph):
    graph['parameter_points'][0]['parameters'][0]['const'] = True
    graph['parameter_points'].append({'name': 'source_snapshot', 'parameters': [{'name': 'mu', 'value': 1}]})
    rows = h.evaluation_points(inspect(graph), selection(parameter_point='source_snapshot'))
    assert rows[0]['constants']['mu'] is False
    assert rows[1]['values']['mu'] == 2


@pytest.mark.parametrize('value', [float('nan'), True, -1, 11])
def test_bad_override(graph, value):
    with pytest.raises(ValueError):
        h.evaluation_points(inspect(graph), selection(points=[{'id': 'p', 'parameters': {'mu': value}}]))


def test_ambiguous_shared_modelconfig_refuses(graph):
    second = copy.deepcopy(graph['analyses'][0]); second['name'] = 'second'
    graph['analyses'].append(second)
    graph['misc']['ROOT_internal']['ModelConfigs']['second'] = {'mcName': 'ModelConfig', 'pdfName': 'different'}
    with pytest.raises(ValueError, match='shared ModelConfig'):
        inspect(graph)


def combined_graph(graph):
    graph['distributions'] = [dict(copy.deepcopy(graph['distributions'][0]), name='model_' + s) for s in ('CR', 'SR')]
    graph['data'] = [dict(copy.deepcopy(graph['data'][0]), name=b + '_' + s) for b in ('obsData', 'asimovData') for s in ('CR', 'SR')]
    graph['likelihoods'] = [{'name': s, 'distributions': ['model_CR', 'model_SR'], 'data': [s + '_CR', s + '_SR']} for s in ('obsData', 'asimovData')]
    graph['analyses'] = [dict(copy.deepcopy(graph['analyses'][0]), name=s, likelihood=s) for s in ('obsData', 'asimovData')]
    meta = {'index_cat': 'channelCat', 'labels': ['CR', 'SR'], 'indices': [1, 0]}
    graph['misc']['ROOT_internal'] = {
      'ModelConfigs': {s: {'mcName': 'ModelConfig', 'pdfName': 'simPdf'} for s in ('obsData', 'asimovData')},
      'combined_distributions': {'simPdf': dict(meta, distributions=['model_CR', 'model_SR'])},
      'combined_datasets': {s: dict(meta) for s in ('obsData', 'asimovData')}}
    return graph


def test_both_original_analysis_selections_keep_exact_data(graph):
    g = inspect(combined_graph(graph))
    assert g['bindings']['obsData']['dataset'] == 'obsData'
    assert g['bindings']['asimovData']['dataset'] == 'asimovData'
    assert g['bindings']['obsData']['category']['indices'] == [1, 0]


@pytest.mark.parametrize('mutation', [
    lambda g: g['misc']['ROOT_internal']['combined_datasets']['obsData'].update(labels=['SR', 'CR']),
    lambda g: g['misc']['ROOT_internal']['combined_datasets'].update(extra={'index_cat': 'channelCat', 'labels': ['missing'], 'indices': [0]}),
    lambda g: g['misc']['ROOT_internal']['combined_distributions']['simPdf'].update(indices=[1, 1]),
])
def test_combined_extra_missing_or_wrong_channel_refuses(graph, mutation):
    g = combined_graph(graph)
    # An extra declaration lacking source components is itself refused, even if
    # it is outside the selected likelihood; ROOT imports the complete graph.
    mutation(g)
    with pytest.raises(ValueError):
        inspect(g)


def test_selected_domain_narrower_than_default_refuses(graph):
    graph['domains'][1]['axes'][0]['max'] = 1.5
    with pytest.raises(ValueError, match='selected analysis domain'):
        h.evaluation_points(inspect(graph), selection())


@pytest.mark.parametrize('point_name', ['default_values', 'named_snapshot'])
def test_complete_baseline_outside_selected_domain_refuses(graph, point_name):
    graph['domains'][1]['axes'][0]['max'] = 1.5
    if point_name == 'default_values':
        graph['parameter_points'][0]['parameters'][0]['value'] = 2
    else:
        graph['parameter_points'].append({'name': point_name, 'parameters': [{'name': 'mu', 'value': 2}]})
    with pytest.raises(ValueError, match='selected analysis domain'):
        h.evaluation_points(inspect(graph), selection(parameter_point=point_name, points=[{'id': 'empty_override', 'parameters': {}}]))


def test_valid_partial_named_snapshot_checks_full_merged_point(graph):
    graph['parameter_points'].append({'name': 'valid', 'parameters': [{'name': 'mu', 'value': 1.25}]})
    graph['domains'][1]['axes'][0]['max'] = 1.5
    rows = h.evaluation_points(inspect(graph), selection(parameter_point='valid', points=[{'id': 'p', 'parameters': {}}]))
    assert rows[0]['values'] == {'mu': 1.25}


def test_function_native_type_retained(graph):
    graph['functions'] = [{'name': 'nonlinear', 'type': 'sum', 'summands': ['mu', 'mu']}]
    assert inspect(graph)['document']['functions'] == graph['functions']
    graph['functions'][0]['type'] = 'unknown'
    with pytest.raises(ValueError, match='unsupported native importer'):
        inspect(graph)


def test_native_true_write_success(tmp_path):
    tool = SimpleNamespace(exportJSON=lambda _: True)
    n.retain_workspace(SimpleNamespace(writeToFile=lambda _: True), tool, tmp_path)
    with pytest.raises(ValueError, match='ROOT retention'):
        n.retain_workspace(SimpleNamespace(writeToFile=lambda _: False), tool, tmp_path)
    with pytest.raises(ValueError, match='HS3 export'):
        n.retain_workspace(SimpleNamespace(writeToFile=lambda _: True), SimpleNamespace(exportJSON=lambda _: False), tmp_path)


class Var:
    def __init__(self, name, value, constant=False, low=0, high=10):
        self.name, self.value, self.constant, self.low, self.high = name, value, constant, low, high
    def GetName(self): return self.name
    def getVal(self): return self.value
    def setVal(self, value): self.value = value
    def isConstant(self): return self.constant
    def setConstant(self, value): self.constant = value
    def getMin(self, *args): return self.low
    def getMax(self, *args): return self.high


def test_native_full_reset_per_point(graph):
    vs = {'mu': Var('mu', 1), 'native_implicit': Var('native_implicit', 3, True)}
    class Nll:
        def getVal(self):
            result = vs['mu'].value + vs['native_implicit'].value
            vs['native_implicit'].value = 999 # adversarial state left by evaluation
            return result
    ROOT = SimpleNamespace(ravel_hs3_v1=SimpleNamespace(nll=lambda *_: Nll()), SetOwnership=lambda *_: None)
    ws = SimpleNamespace(allVars=lambda: list(vs.values()), var=lambda name: vs.get(name), arg=lambda name: vs.get(name))
    rows = n.evaluate(ROOT, ws, None, None, {'points': h.evaluation_points(inspect(graph), selection())})
    assert [r['nll'] for r in rows] == [4, 5]
    assert [r['delta_nll_from_first'] for r in rows] == [0, 1]


def test_native_observed_image_refuses_unrelated_bytes(tmp_path, monkeypatch):
    a = tmp_path / 'libCore.6.40.04.so'; a.write_bytes(b'bound')
    root = tmp_path / 'ROOT.py'; root.write_bytes(b'module')
    cpp = tmp_path / 'cppyy.py'; cpp.write_bytes(b'module2')
    pin = lambda p: {'path': str(p), 'sha256': h.digest(p)}
    runtime = {'modules': {'ROOT': pin(root), 'cppyy': pin(cpp)}, 'loaded_libraries': {'libCore': pin(a)}, 'root_version': '6.40.04', 'environment': dict(h.os.environ), 'artifacts': [pin(a), pin(root), pin(cpp)]}
    monkeypatch.setattr(n, 'images', lambda: [str(a)])
    ROOT = SimpleNamespace(__file__=str(root), gROOT=SimpleNamespace(GetVersion=lambda: '6.40.04'))
    cppyy = SimpleNamespace(__file__=str(cpp))
    observed = n.runtime_identity(ROOT, cppyy, runtime)
    assert observed['required_loaded_images']['libCore'] == pin(a)
    a.write_bytes(b'changed')
    with pytest.raises(ValueError, match='OS-loaded'):
        n.runtime_identity(ROOT, cppyy, runtime)


def test_native_both_selection_data_and_every_bin(graph):
    g = inspect(graph); binding = g['bindings']['analysis']
    x = Var('x', .5)
    class Data:
        weights = [12, 23]
        def GetName(self): return 'obsData'
        def sumEntries(self): return sum(self.weights)
        def numEntries(self): return 2
        def get(self, i): self.i = i; x.value = i + .5; return SimpleNamespace(find=lambda _: x)
        def weight(self): return self.weights[self.i]
    data = Data(); mu = Var('mu', 1)
    mc = SimpleNamespace(GetName=lambda: 'ModelConfig', GetPdf=lambda: SimpleNamespace(GetName=lambda: 'model'),
       GetParametersOfInterest=lambda: [mu], GetExternalConstraints=lambda: [], GetNuisanceParameters=lambda: [], GetGlobalObservables=lambda: [])
    ws = SimpleNamespace(pdf=lambda _: True, var=lambda _: mu, arg=lambda _: mu)
    n.check_workspace(ws, mc, data, g, binding)
    data.weights = [13, 22] # same total cannot hide changed shape
    with pytest.raises(ValueError, match='dataset bin'):
        n.check_workspace(ws, mc, data, g, binding)


def test_no_root_import_from_admission(graph, monkeypatch):
    monkeypatch.setitem(sys.modules, 'ROOT', None)
    assert inspect(graph)['inventory']['counts']['analyses'] == 1


@pytest.fixture
def configured(tmp_path, graph):
    model = tmp_path / 'original.json'; model.write_text(json.dumps(graph))
    provenance = tmp_path / 'provenance.json'; provenance.write_text('{"synthetic":true}')
    binary = tmp_path / 'python'; binary.write_text('#!/bin/sh\nexit 99\n'); binary.chmod(0o755)
    artifact = tmp_path / 'synthetic-ABI'; artifact.write_text('Portable admission only, never loaded')
    # Closed synthetic source evidence for portable lifecycle controls. Actual
    # upstream registry/source bytes are separately checked in the 118-model
    # census and prospective native plans; this test must not require local runs.
    primary = tmp_path / 'synthetic-primary'; primary.mkdir()
    source_text = {
       'JSONFactories_HistFactory.cxx': 'registerImporter<Synthetic>("histfactory_dist", true);',
       'JSONFactories_RooFitCore.cxx': 'registerImporter<Synthetic>("gaussian_dist", true);',
       'RooFitHS3_wsfactoryexpressions.cxx': 'R"({"sum": {}})"',
       'RooJSONFactoryWSTool.cxx': '// Synthetic portable admission; never compiled',
       'Domains.cxx': '// Synthetic portable admission; never compiled',
       'ModelConfig.cxx': '// Synthetic portable admission; never compiled'}
    sources = []
    for name, content in source_text.items():
        path = primary / name; path.write_text(content); sources.append(path)
    pin = lambda p: {'path': str(p), 'sha256': h.digest(p)}
    c = {'schema_version': 1, 'source': 'Synthetic portable source/lifecycle control; no native compatibility claim',
       'max_seconds': 10, 'model': pin(model), 'provenance': [pin(provenance)],
       'selection': selection(), 'nll': {'extended': True, 'offset': False, 'eval_backend': 'legacy', 'num_cpu': 1,
        'constraints': 'all_pdf_parameters', 'global_observables_source': 'model'},
       'runtime': {'python': pin(binary), 'artifacts': [pin(artifact)], 'importer_sources': [pin(p) for p in sources],
         'modules': {'ROOT': pin(artifact), 'cppyy': pin(artifact)},
         'loaded_libraries': {s: pin(artifact) for s in ('libCore', 'libRooFitCore', 'libRooFitHS3', 'libHistFactory')},
         'root_version': '6.40.04', 'environment': {'PATH': '/usr/bin:/bin', 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONCOERCECLOCALE': '0', 'LC_CTYPE': 'C'},
         'importer_config': {'allowExportInvalidNames': False, 'allowSanitizeNames': False, 'importNoDomainParametersAsRooConstVars': True}}}
    cp = tmp_path / 'configuration.json'; cp.write_text(json.dumps(c))
    return cp, c, model, sources


def study(cp):
    policy = {'schema_version': 1, 'actors': {'proposer': 'producer', 'executor': 'producer', 'physics_critic': 'critic', 'skeptical_verifier': 'verifier', 'physics_decider': 'decider'},
       'max_redos': 0, 'allowed_changed_paths': [], 'allowed_stages': ['science'],
       'required_checks': [{'id': 'identity', 'kind': 'integrity'}, {'id': 'native_graph', 'kind': 'scientific'}],
       'claim_scopes': {'diagnostic': {'checks': ['identity', 'native_graph'], 'actions': ['delivery', 'reuse']}}}
    return {'schema_version': 2, 'mode': 'hs3-likelihood', 'source': 'Synthetic HS3 public planning control only',
       'assumptions': ['No ROOT import or scientific execution occurs in this portable test.'], 'max_seconds': 20,
       'approval_mode': 'scripted_yes', 'max_attempts': 1, 'task': {'input': str(cp)},
       'review_policy': {'schema_version': 1, 'policy': policy, 'correction_contract': {'task_fields': [], 'input_slots': []}}}


def test_actual_public_plan_verify_and_full_inputs(configured, tmp_path, monkeypatch):
    from ravel.workflow import science
    monkeypatch.setitem(sys.modules, 'ROOT', None)
    cp, c, model, sources = configured
    spec = tmp_path / 'science.json'; spec.write_text(json.dumps(study(cp)))
    expected = set(h.inputs({'input': str(cp)}, tmp_path))
    assert {cp, model, *sources} <= expected
    assert Path(h.__file__).resolve() in expected
    assert Path(n.__file__).resolve() in expected
    run = tmp_path / 'study'
    plan = science.plan(run, spec)
    verified = science.verify_plan(run)
    assert verified['stage_binding']['fingerprint'] == plan['stage_binding']['fingerprint']
    assert not (run / 'inputs/science-approval.json').exists()
    assert not (run / 'outputs/attempt-1').exists()
    model.write_text(model.read_text() + '\n')
    with pytest.raises(ValueError, match='changed HS3'):
        science.verify_plan(run)


def test_public_budget_and_legacy_scope_refuse(configured, tmp_path):
    from ravel.workflow import science
    cp, c, *_ = configured
    s = study(cp); s['max_seconds'] = 5
    source = tmp_path / 's.json'; source.write_text(json.dumps(s))
    with pytest.raises(ValueError, match='budget exceeds'):
        science.plan(tmp_path / 'short', source)
    s = study(cp); s['schema_version'] = 1; del s['max_attempts']; del s['review_policy']
    source.write_text(json.dumps(s))
    with pytest.raises(ValueError, match='prospective version 2'):
        science.plan(tmp_path / 'legacy', source)


def test_adapter_retains_failed_native_without_retry(configured, tmp_path, monkeypatch):
    cp, c, *_ = configured
    calls = []
    def refuse(argv, **kwargs):
        calls.append((argv, kwargs)); return SimpleNamespace(returncode=7)
    monkeypatch.setattr(h.subprocess, 'run', refuse)
    result = h.run({'input': str(cp)}, tmp_path, tmp_path / 'owned-output')
    assert result['status'] == 'failed' and result['runtime_qualified_for_this_model'] is False
    assert len(calls) == 1 and calls[0][1]['env'] == c['runtime']['environment']
    assert (tmp_path / 'owned-output/original-hs3.json').read_bytes() == (tmp_path / 'original.json').read_bytes()
    assert (tmp_path / 'owned-output/native-combined.log').stat().st_size > 0
    assert (tmp_path / 'owned-output/native-request.json').is_file()


def native_delivery(configured, tmp_path):
    cp, c, model, sources = configured
    g = h.inspect_graph(model.read_bytes(), h.source_types(sources))
    pts = h.evaluation_points(g, c['selection'])
    request = {'configuration': c, 'model_sha256': h.digest(model), 'inventory': g['inventory'],
        'binding': g['bindings']['analysis'], 'points': pts, 'output': str(tmp_path)}
    phase = {'root_version': c['runtime']['root_version'], 'modules': c['runtime']['modules'],
      'required_loaded_images': c['runtime']['loaded_libraries'], 'environment': c['runtime']['environment'],
      'cwd': str(tmp_path), 'python': c['runtime']['python']}
    result = {'status': 'passed', 'model_sha256': request['model_sha256'], 'binding': request['binding'],
      'root_version': c['runtime']['root_version'], 'source_export_metadata': g['inventory']['hs3_metadata'],
      'nll_options': c['nll'], 'native_helper_sha256': hashlib.sha256(n.HELPER.encode()).hexdigest(),
      'runtime_before': copy.deepcopy(phase), 'runtime_after': copy.deepcopy(phase), 'evaluations': [
        {'id': p['id'], 'source_overrides': p['overrides'], 'source_assignments': {name: {'value': v, 'constant': p['constants'][name]} for name, v in p['values'].items()},
         'nll': value, 'delta_nll_from_first': value - 5.0} for p, value in zip(pts, (5.0, 6.0))]}
    return request, result


def test_complete_native_result_rebind(configured, tmp_path):
    req, result = native_delivery(configured, tmp_path)
    h.validate_native(result, req)


@pytest.mark.parametrize('change', [
    lambda r: r.update(root_version='6.35.01'),
    lambda r: r.update(model_sha256='0' * 64),
    lambda r: r['binding'].update(dataset='otherData'),
    lambda r: r['runtime_after']['required_loaded_images']['libCore'].update(sha256='0' * 64),
    lambda r: r['runtime_before']['environment'].update(ambient='unapproved'),
    lambda r: r['evaluations'].pop(),
    lambda r: r['evaluations'].reverse(),
    lambda r: r['evaluations'][0]['source_assignments']['mu'].update(constant=True),
    lambda r: r['evaluations'][0]['source_assignments']['mu'].update(value=9),
    lambda r: r['evaluations'][0].update(nll=float('nan')),
    lambda r: r['evaluations'][1].update(delta_nll_from_first=9),
    lambda r: r['nll_options'].update(constraints='none'),
])
def test_changed_native_delivery_refuses(configured, tmp_path, change):
    req, result = native_delivery(configured, tmp_path)
    # Native output is an independent document, never the request object.
    result = copy.deepcopy(result)
    change(result)
    with pytest.raises(ValueError):
        h.validate_native(result, req)
