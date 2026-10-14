"""Bound child program used by hs3_likelihood under ordinary supervision.

Importing this Python module never imports ROOT. main() is a native scientific
operation and is reached only by the approved scientific-study adapter.
"""
from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys

# Source-bound tiny Cling bridge: enumerate the native importer registry and use
# ModelConfig's own conditional/global/external-constraint construction. Passing
# every PDF parameter to Constrain retains even source-fixed constraint factors.
HELPER = r'''
#include <RooFitHS3/JSONIO.h>
#include <RooFit/ModelConfig.h>
#include <RooAbsPdf.h>
#include <RooAbsReal.h>
#include <RooAbsData.h>
#include <RooGlobalFunc.h>
#include <vector>
#include <string>
namespace ravel_hs3_v1 {
std::vector<std::string> types() {
  std::vector<std::string> out;
  for (auto const& p : RooFit::JSONIO::importers()) out.push_back(p.first);
  for (auto const& p : RooFit::JSONIO::importExpressions()) out.push_back(p.first);
  return out;
}
RooAbsReal* nll(RooStats::ModelConfig& mc, RooAbsData& data) {
  auto pars = mc.GetPdf()->getParameters(*data.get());
  return mc.createNLL(data, RooFit::Constrain(*pars), RooFit::Extended(true),
    RooFit::Offset(false), RooFit::EvalBackend("legacy"), RooFit::NumCPU(1),
    RooFit::GlobalObservablesSource("model")).release();
}
}
'''


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n')


def arg_names(collection):
    return sorted(str(a.GetName()) for a in collection) if collection else []


def images():
    """Observe OS-loaded images in this process, not a producer-reported path."""
    if sys.platform == 'darwin':
        lib = ctypes.CDLL(None)
        lib._dyld_image_count.restype = ctypes.c_uint32
        lib._dyld_get_image_name.argtypes = [ctypes.c_uint32]
        lib._dyld_get_image_name.restype = ctypes.c_char_p
        return sorted({os.fsdecode(lib._dyld_get_image_name(i)) for i in range(lib._dyld_image_count()) if lib._dyld_get_image_name(i)})
    if sys.platform.startswith('linux'):
        return sorted({line.split(maxsplit=5)[5].strip() for line in Path('/proc/self/maps').read_text().splitlines() if len(line.split(maxsplit=5)) == 6 and line.split(maxsplit=5)[5].startswith('/')})
    raise ValueError('native loaded-image observer supports Darwin and Linux only')


def runtime_identity(ROOT, cppyy, runtime):
    if dict(os.environ) != runtime['environment']:
        raise ValueError('native import/evaluation changed the declared environment')
    observed_modules = {}
    for name, module in (('ROOT', ROOT), ('cppyy', cppyy)):
        actual = Path(module.__file__).resolve()
        pin = runtime['modules'][name]
        if str(actual) != pin['path'] or digest(actual) != pin['sha256']:
            raise ValueError('actual native module origin/hash mismatch: ' + name)
        observed_modules[name] = {'path': str(actual), 'sha256': digest(actual)}
    loaded = images()
    qualified = {}
    for prefix, pin in runtime['loaded_libraries'].items():
        matches = sorted({str(Path(p).resolve()) for p in loaded if Path(p).name.startswith(prefix + '.')})
        if matches != [pin['path']] or digest(matches[0]) != pin['sha256']:
            raise ValueError('actual OS-loaded native image mismatch: ' + prefix)
        qualified[prefix] = {'path': matches[0], 'sha256': digest(matches[0])}
    version = str(ROOT.gROOT.GetVersion()).replace('/', '.')
    if version != runtime['root_version']:
        raise ValueError('actual ROOT version mismatch: ' + version)
    module_files = {p['path']: p['sha256'] for p in runtime['artifacts']}
    imported_modules = {}
    for name, module in sorted(sys.modules.copy().items()):
        if name.startswith(('ROOT.', 'cppyy.')) and getattr(module, '__file__', None):
            p = str(Path(module.__file__).resolve())
            if p not in module_files or digest(p) != module_files[p]:
                raise ValueError('unbound actual native Python source module: ' + name)
            imported_modules[name] = {'path': p, 'sha256': module_files[p]}
    return {'root_version': version, 'modules': observed_modules, 'required_loaded_images': qualified,
            'actual_native_module_census': imported_modules,
            'all_os_image_spellings': loaded, 'platform': platform.platform(), 'pid': os.getpid(),
            'python': {'path': str(Path(sys.executable).resolve()), 'sha256': digest(sys.executable)},
            'environment': dict(os.environ), 'cwd': str(Path.cwd()), 'flags': repr(sys.flags)}


def variable(v):
    value = float(v.getVal())
    if not math.isfinite(value):
        raise ValueError('nonfinite imported native parameter: ' + str(v.GetName()))
    # Preserve explicit infinite range status rather than encode nonfinite JSON.
    low, high = float(v.getMin()), float(v.getMax())
    return {'name': str(v.GetName()), 'value': value, 'constant': bool(v.isConstant()),
            'min': low if math.isfinite(low) else None, 'max': high if math.isfinite(high) else None,
            'min_status': 'finite' if math.isfinite(low) else 'unbounded',
            'max_status': 'finite' if math.isfinite(high) else 'unbounded'}


def data_inventory(ROOT, d):
    rows = []
    for i in range(int(d.numEntries())):
        observables = d.get(i)
        coordinates = {}
        for v in observables:
            coordinates[str(v.GetName())] = ({'label': str(v.getLabel()), 'index': int(v.getIndex())}
               if v.InheritsFrom('RooAbsCategory') else {'value': float(v.getVal())})
        w, w2 = float(d.weight()), float(d.weightSquared())
        err = float(d.weightError(ROOT.RooAbsData.SumW2))
        rows.append({'index': i, 'coordinates': coordinates, 'weight': w,
                     'weight_squared': w2 if math.isfinite(w2) else None,
                     'native_sumw2_error': err if math.isfinite(err) else None,
                     'error_status': 'finite' if math.isfinite(err) else 'native_nonfinite'})
    return {'name': str(d.GetName()), 'class': str(d.ClassName()), 'entries': int(d.numEntries()),
            'sum_weights': float(d.sumEntries()), 'observables': arg_names(d.get()), 'rows': rows}


def workspace_inventory(ROOT, ws, mc, dataset):
    pdf = mc.GetPdf()
    return {'variables': [variable(v) for v in ws.allVars()],
            'functions': [{'name': str(v.GetName()), 'class': str(v.ClassName())} for v in ws.allFunctions()],
            'pdfs': [{'name': str(v.GetName()), 'class': str(v.ClassName())} for v in ws.allPdfs()],
            'datasets': [data_inventory(ROOT, d) for d in ws.allData()],
            'model_config': {'name': str(mc.GetName()), 'pdf': str(pdf.GetName()),
              'parameters_of_interest': arg_names(mc.GetParametersOfInterest()),
              'nuisance_parameters': arg_names(mc.GetNuisanceParameters()),
              'global_observables': arg_names(mc.GetGlobalObservables()),
              'conditional_observables': arg_names(mc.GetConditionalObservables()),
              'external_constraints': arg_names(mc.GetExternalConstraints()),
              'observables': arg_names(mc.GetObservables())},
            'selected_dataset': {'name': str(dataset.GetName()), 'entries': int(dataset.numEntries()), 'sum_weights': float(dataset.sumEntries())}}


def check_workspace(ws, mc, dataset, graph, binding):
    if not mc or not dataset or not mc.GetPdf():
        raise ValueError('native selected ModelConfig/PDF/dataset absent')
    if str(mc.GetName()) != binding['model_config'] or str(mc.GetPdf().GetName()) != binding['pdf'] or str(dataset.GetName()) != binding['dataset']:
        raise ValueError('actual selected native objects differ from original source binding')
    if arg_names(mc.GetParametersOfInterest()) != binding['parameters_of_interest']:
        raise ValueError('native ModelConfig POI differs from source')
    if arg_names(mc.GetExternalConstraints()) != sorted(binding['external_constraints']):
        raise ValueError('native external constraints differ from source')
    expected_domain = set(binding['domain_parameters'])
    # ROOT determines nuisance/global partition from PDF dependencies and native
    # constant flags. Retain both complete sets and refuse any added domain role.
    for c in (mc.GetNuisanceParameters(), mc.GetGlobalObservables()):
        if not set(arg_names(c)) <= expected_domain:
            raise ValueError('native role set contains an unbound domain parameter')
    for n in binding['distributions']:
        if not ws.pdf(n):
            raise ValueError('original source distribution not imported: ' + n)
    for n, a in graph['domains']['default_domain'].items():
        v = ws.var(n)
        if not v:
            raise ValueError('source default-domain variable not imported: ' + n)
        for field, actual in (('min', v.getMin()), ('max', v.getMax())):
            if a.get(field) is not None and float(actual) != float(a[field]):
                raise ValueError('native default-domain bound differs from source: ' + n)
    for n, source in graph['points']['default_values'].items():
        v = ws.arg(n)
        if not v or float(v.getVal()) != float(source['value']):
            raise ValueError('native imported default parameter value differs from source: ' + n)
        if ws.var(n) and bool(v.isConstant()) != bool(source.get('const', False)):
            raise ValueError('native default parameter constant flag differs from source: ' + n)
    for dn in binding['domain_names']:
        for n, a in graph['domains'][dn].items():
            v = ws.var(n)
            if v:
                for field, actual in (('min', v.getMin(dn)), ('max', v.getMax(dn))):
                    if a.get(field) is not None and float(actual) != float(a[field]):
                        raise ValueError('native named domain bound differs from source: ' + dn + '/' + n)
    category = binding['category']
    source_data = graph['tables']['data']
    expected = sum(sum(source_data[n]['contents']) for n in binding['data_components'])
    if not math.isclose(float(dataset.sumEntries()), expected, rel_tol=1e-12, abs_tol=1e-8):
        raise ValueError('native dataset total differs from all original source bins')
    # Inspect every imported data entry, including zero-weight bins. Multi-channel
    # RooDataSet rows may be sparse; the complete source-to-native bin map is
    # tested by aggregation, with any missing positive bin or new bin refused.
    aggregated = {}
    for i in range(int(dataset.numEntries())):
        row = dataset.get(i)
        weight = float(dataset.weight())
        if not math.isfinite(weight):
            raise ValueError('nonfinite native dataset weight')
        if category:
            cat = row.find(category['index_cat'])
            if not cat:
                raise ValueError('source combined category absent from data')
            label = str(cat.getLabel())
            if label not in category['labels'] or int(cat.getIndex()) != category['indices'][category['labels'].index(label)]:
                raise ValueError('native category label/index differs from source')
            dn = binding['dataset'] + '_' + label
        else:
            dn = binding['data_components'][0]
        r = source_data[dn]
        index = 0
        for axis in r['axes']:
            v = row.find(axis['name'])
            if not v:
                raise ValueError('source data observable absent')
            # v1 admits source bins represented explicitly by edges. Product
            # domain nbins remains supported independently for parameters.
            edges = axis.get('edges')
            if not edges:
                raise ValueError('native data reconciliation requires explicit original edges')
            x = float(v.getVal())
            matches = [j for j, (lo, hi) in enumerate(zip(edges, edges[1:])) if lo <= x < hi]
            if len(matches) != 1:
                raise ValueError('native data coordinate outside original bins')
            index = index * (len(edges) - 1) + matches[0]
        aggregated[(dn, index)] = aggregated.get((dn, index), 0.0) + weight
    for dn in binding['data_components']:
        for j, w in enumerate(source_data[dn]['contents']):
            if not math.isclose(aggregated.pop((dn, j), 0.0), w, rel_tol=1e-12, abs_tol=1e-8):
                raise ValueError('native dataset bin differs from original source')
    if aggregated:
        raise ValueError('extra native data bin')


def evaluate(ROOT, ws, mc, dataset, request):
    baseline = [variable(v) for v in ws.allVars()]
    nll = ROOT.ravel_hs3_v1.nll(mc, dataset)
    if not nll:
        raise ValueError('native complete ModelConfig NLL construction failed')
    ROOT.SetOwnership(nll, True)
    rows = []
    for point in request['points']:
        # Reset all imported real variables for EVERY point, including native
        # implicit globals/constants not listed in the HS3 parameter snapshot.
        for row in baseline:
            v = ws.var(row['name']); v.setVal(row['value']); v.setConstant(row['constant'])
        for name, value in point['values'].items():
            v = ws.var(name)
            if not v:
                arg = ws.arg(name)
                if not arg or not arg.isConstant() or float(arg.getVal()) != float(value) or name in point['overrides']:
                    raise ValueError('source point parameter not represented faithfully in native workspace: ' + name)
                continue
            v.setVal(value); v.setConstant(point['constants'][name])
            if float(v.getVal()) != float(value):
                raise ValueError('native parameter assignment changed requested value: ' + name)
        assigned = {name: {'value': float(ws.arg(name).getVal()), 'constant': bool(ws.arg(name).isConstant())} for name in point['values']}
        if assigned != {name: {'value': value, 'constant': point['constants'][name]} for name, value in point['values'].items()}:
            raise ValueError('native point assignment does not preserve every source value/constant flag')
        value = float(nll.getVal())
        if not math.isfinite(value):
            raise ValueError('nonfinite native NLL at ' + point['id'])
        rows.append({'id': point['id'], 'nll': value, 'parameters': [variable(v) for v in ws.allVars()], 'source_overrides': point['overrides'], 'source_assignments': assigned})
    for row in rows:
        row['delta_nll_from_first'] = row['nll'] - rows[0]['nll']
    return rows


def check_derivative_axes(ws, mc, plan):
    """No POI/nuisance label is inferred from a merely floating source value."""
    if plan is None:
        return
    allowed = set(arg_names(mc.GetParametersOfInterest())) | set(arg_names(mc.GetNuisanceParameters()))
    forbidden = (set(arg_names(mc.GetGlobalObservables())) | set(arg_names(mc.GetConditionalObservables()))
                 | set(arg_names(mc.GetObservables())))
    for name in plan['axis_order']:
        if name not in allowed or name in forbidden or not ws.var(name):
            raise ValueError('native derivative axis must be an actual continuous ModelConfig POI/nuisance: ' + name)


def retain_workspace(ws, tool, out):
    if not tool.exportJSON(str(out / 'native-roundtrip-hs3.json')):
        raise ValueError('native complete workspace HS3 export failed')
    # RooWorkspace::writeToFile returns TRUE on success (the source explicitly
    # documents and implements this convention).
    if not ws.writeToFile(str(out / 'imported-workspace.root')):
        raise ValueError('native workspace ROOT retention failed')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if sys.flags.optimize or len(argv) != 1:
        raise ValueError('one native request under unoptimized Python required')
    request = json.loads(Path(argv[0]).read_text())
    out = Path(request['output'])
    if Path.cwd() != out:
        raise ValueError('actual native cwd differs from owned output')
    if digest(__file__) != request['worker_sha256'] or digest(out / 'hs3_contract.py') != request['contract_sha256'] or digest(request['model']) != request['model_sha256']:
        raise ValueError('staged native worker/contract/original graph byte drift')
    spec = importlib.util.spec_from_file_location('hs3_contract', out / 'hs3_contract.py')
    contract = importlib.util.module_from_spec(spec); spec.loader.exec_module(contract)
    graph = contract.inspect_graph(Path(request['model']).read_bytes(), request['supported_types'])
    points, derivative_plan = contract.configured_points(request['configuration'], graph)
    if graph['inventory'] != request['inventory'] or points != request['points'] or derivative_plan != request.get('derivative_plan'):
        raise ValueError('native request differs from original graph/points')
    if derivative_plan is not None and digest(out / 'native_likelihood_derivatives.py') != request['derivative_kernel_sha256']:
        raise ValueError('staged derivative kernel byte drift')
    runtime = request['configuration']['runtime']
    if dict(os.environ) != runtime['environment'] or str(Path(sys.executable).resolve()) != runtime['python']['path']:
        raise ValueError('actual native interpreter/environment differs from exact launch envelope')
    for p in [runtime['python'], *runtime['artifacts'], *runtime['importer_sources']]:
        if digest(p['path']) != p['sha256']:
            raise ValueError('native input byte drift before ROOT import')
    import ROOT
    import cppyy
    # Loading exact admitted libraries occurs inside the same supervised process.
    for pin in runtime['loaded_libraries'].values():
        if ROOT.gSystem.Load(pin['path']) < 0:
            raise ValueError('required native library cannot load')
    before = runtime_identity(ROOT, cppyy, runtime)
    ws = ROOT.RooWorkspace('ravel_hs3', 'Original supplied HS3 model')
    tool = ROOT.RooJSONFactoryWSTool(ws)
    cfg = ROOT.RooJSONFactoryWSTool.config()
    for k, value in runtime['importer_config'].items():
        setattr(cfg, k, value)
    if not ROOT.gInterpreter.Declare(HELPER):
        raise ValueError('source-bound native HS3 identity/NLL bridge failed to compile')
    observed_types = sorted({str(s) for s in ROOT.ravel_hs3_v1.types()})
    if not set(graph['inventory']['types']) <= set(observed_types):
        raise ValueError('original graph has unsupported actual native importer types')
    if not tool.importJSON(request['model']):
        raise ValueError('native original HS3 import failed')
    binding = request['binding']; mc = ws.obj(binding['model_config']); data = ws.data(binding['dataset'])
    check_workspace(ws, mc, data, graph, binding)
    check_derivative_axes(ws, mc, derivative_plan)
    inventory = workspace_inventory(ROOT, ws, mc, data)
    write(out / 'imported-workspace-inventory.json', inventory)
    retain_workspace(ws, tool, out)
    rows = evaluate(ROOT, ws, mc, data, request)
    after = runtime_identity(ROOT, cppyy, runtime)
    for p in [runtime['python'], *runtime['artifacts'], *runtime['importer_sources']]:
        if digest(p['path']) != p['sha256']:
            raise ValueError('native source/runtime byte drift during import/evaluation')
    if digest(request['model']) != request['model_sha256']:
        raise ValueError('original staged HS3 graph drift')
    if derivative_plan is not None and (digest(out / 'native_likelihood_derivatives.py') != request['derivative_kernel_sha256']
            or digest(__file__) != request['worker_sha256'] or digest(out / 'hs3_contract.py') != request['contract_sha256']):
        raise ValueError('staged derivative kernel/worker/contract drift during evaluation')
    write(out / 'native-evaluation.json', {'status': 'passed', 'physics_validated': False,
          'model_sha256': request['model_sha256'], 'binding': binding,
          'root_version': runtime['root_version'], 'source_export_metadata': graph['inventory']['hs3_metadata'],
          'runtime_before': before, 'runtime_after': after, 'observed_importer_types': observed_types,
          'native_helper_sha256': hashlib.sha256(HELPER.encode()).hexdigest(), 'nll_options': request['configuration']['nll'],
          'workspace_inventory': inventory, 'evaluations': rows,
          **({'derivative_plan_sha256': derivative_plan['plan_sha256']} if derivative_plan is not None else {}),
          'roundtrip_scope': 'Native export retained; semantic equivalence is not inferred from export success.'})
    print(json.dumps({'status': 'passed', 'native_points': len(rows), 'model_sha256': request['model_sha256']}), flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': {'type': type(exc).__name__, 'message': str(exc)}}), file=sys.stderr, flush=True)
        sys.exit(2)
