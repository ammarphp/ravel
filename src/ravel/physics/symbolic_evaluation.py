"""Source-bound HEPTAPOD/FeynCalc evaluation through ordinary studies.

The external GPL parser/converter remain supplied, authenticated dependencies.
RAVEL adapts transport to a fresh direct kernel and canonical InputForm sidecars.
No native or optional symbolic library is imported by intake or inspection.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import json
import keyword
import math
import os
from pathlib import Path
import re
import sys
import time
from types import ModuleType

from ravel.physics import model_tool_bridge as custody
from ravel.workflow.operation_resources import document, document_pin

REVISION = '705b03cc36d96a79107df28d053a23d3fac1d393'
BACKEND = {
    'wolfram_runner.py': 'ad757aff5dd3cc57b56c95895c9c76e45c37b0a92633a926cc2ea49e1860b4a3',
    'symbolic_to_python.py': 'a94cac117fd6fd5cbc3e6f3ac69096239cb43a9b43d751f0cd1f6726936cf2bb',
    'LICENSE.txt': '6e37b70c463bb45b9c817f667eddbc799259d449ae9cb7b3d8a81659203e0279',
    'AUTHORS.txt': 'dbff84de17667491a5604b04f7e823a17ddadc6c5d86885d2dcefcd9cb91f3b1',
}
SCOPE = 'source_bound_symbolic_and_python_delivery'
# Suppress init programs without changing the caller's existing user/license location.
INIT_ENVIRONMENT = ('WOLFRAMINIT', 'MATHKERNELINIT')
_IDENTITY = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')
_WLSYMBOL = re.compile(r'(?:[A-Za-z][A-Za-z0-9]*`)*[A-Za-z$][A-Za-z0-9$]*\Z')


def _text(value, label, maximum=8192):
    if type(value) is not str or not value.strip() or len(value.encode()) > maximum:
        raise ValueError('bounded nonempty ' + label + ' required')
    return value


def _id(value):
    if type(value) is not str or not _IDENTITY.fullmatch(value):
        raise ValueError('simple distinct result/variable identity required')
    return value


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('finite real component required')
    return value


def _pair(value):
    custody._keys(value, ('real', 'imag'), 'complex pair')
    return complex(_number(value['real']), _number(value['imag']))


def validate(task):
    custody._keys(task, ('input', 'input_sha256'), 'symbolic-evaluation task')
    _text(task['input'], 'input path')
    if type(task['input_sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', task['input_sha256']):
        raise ValueError('exact input digest required')
    return deepcopy(task)


def validate_config(c):
    fields = ('schema_version', 'backend_revision', 'source', 'original_task',
        'trusted_executable_sources', 'kernel', 'application_metadata', 'provider_tree',
        'provider_entry', 'provider_version_symbol', 'expected_provider_version',
        'expected_kernel_version', 'script_tree', 'backend_files', 'python_runtime',
        'scripts', 'max_seconds', 'max_ram_mib', 'max_output_bytes')
    custody._keys(c, (*fields, 'feynarts') if c.get('schema_version') == 2 else fields, 'symbolic request')
    if type(c['schema_version']) is not int or c['schema_version'] not in (1,2) or c['backend_revision'] != REVISION:
        raise ValueError('source-bound HEPTAPOD revision/schema required')
    if c['schema_version'] == 2:
        from ravel.physics import feynarts_amplitude
        feynarts_amplitude.addon(c['feynarts'])
        if c['expected_provider_version'] != '10.1.0' or c['provider_version_symbol'] != 'FeynCalc`$FeynCalcVersion':
            raise ValueError('exact inspected FeynCalc10.1.0 package API required')
    if c['trusted_executable_sources'] is not True:
        raise ValueError('explicit trust in supplied executable scripts/provider/converter required')
    _text(c['source'], 'source attribution')
    if c['provider_entry'] != 'FeynCalc/FeynCalc.m':
        raise ValueError('staged package layout must contain FeynCalc/FeynCalc.m')
    if not _WLSYMBOL.fullmatch(c['provider_version_symbol']):
        raise ValueError('declared provider version symbol required')
    _text(c['expected_provider_version'], 'provider version', 128)
    if type(c['expected_kernel_version']) not in (int, float) or not 10 <= c['expected_kernel_version'] < 100:
        raise ValueError('explicit actual kernel version required')
    for key, lo, hi in [('max_seconds', 1, 3600), ('max_ram_mib', 512, 8192),
                        ('max_output_bytes', 1024, 256*1024**2)]:
        if type(c[key]) is not int or not lo <= c[key] <= hi:
            raise ValueError('explicit bounded ' + key + ' required')
    custody._keys(c['backend_files'], BACKEND, 'exact external parser/converter/license files')
    for name, digest in BACKEND.items():
        if c['backend_files'][name].get('sha256') != digest:
            raise ValueError('external backend bytes differ: ' + name)
    custody._keys(c['python_runtime'], ('python', 'sympy_tree', 'mpmath_tree'), 'conversion runtime')
    if type(c['scripts']) is not list or not 1 <= len(c['scripts']) <= 128:
        raise ValueError('complete bounded script batch required')
    script_ids, result_ids = set(), set()
    for s in c['scripts']:
        custody._keys(s, ('id', 'relative_path', 'sha256', 'markers', 'results', 'feynarts_process') if c['schema_version'] == 2 else ('id', 'relative_path', 'sha256', 'markers', 'results'), 'script')
        if _id(s['id']) in script_ids:
            raise ValueError('duplicate script')
        script_ids.add(s['id'])
        rp = Path(s['relative_path'])
        if rp.is_absolute() or '..' in rp.parts or rp.suffix != '.wl':
            raise ValueError('script must be a relative Wolfram file in its captured tree')
        if type(s['markers']) is not dict or set(s['markers']) != {'symbolic', 'numerical', 'latex', 'status'}:
            raise ValueError('complete original marker categories required')
        for category in ('symbolic', 'numerical', 'latex'):
            ids = s['markers'][category]
            if type(ids) is not list or len(ids) > 256 or len(set(ids)) != len(ids):
                raise ValueError('exact unique original marker roster required')
            for key in ids:
                _id(key)
        _text(s['markers']['status'], 'expected original status', 128)
        if type(s['results']) is not list or not 1 <= len(s['results']) <= 256:
            raise ValueError('complete bounded result roster required')
        for r in s['results']:
            custody._keys(r, ('id', 'symbol', 'variables', 'units', 'dimension_GeV',
                'conventions', 'assumptions', 'points', *(['representation'] if c['schema_version'] == 2 else [])), 'symbolic result')
            if _id(r['id']) in result_ids:
                raise ValueError('result identities must be unique throughout batch')
            result_ids.add(r['id'])
            if type(r['symbol']) is not str or not _WLSYMBOL.fullmatch(r['symbol']):
                raise ValueError('source-bound result symbol required; expressions are not selectors')
            _text(r['units'], 'units'); _text(r['conventions'], 'complete vertex/basis/mass/factor conventions')
            if type(r['dimension_GeV']) is not int or not -32 <= r['dimension_GeV'] <= 32:
                raise ValueError('declared integer mass dimension required')
            if type(r['assumptions']) is not list or len(r['assumptions']) > 64:
                raise ValueError('complete supplied assumptions required')
            for a in r['assumptions']:
                _text(a, 'assumption')
            names = []
            if type(r['variables']) is not list or len(r['variables']) > 64:
                raise ValueError('ordered complete variables required; constants may have none')
            for v in r['variables']:
                custody._keys(v, ('name', 'domain', 'units', 'dimension_GeV'), 'variable')
                names.append(_id(v['name']))
                if keyword.iskeyword(v['name']) or v['name'] in ('math', 'conjugate'):
                    raise ValueError('variable collides with Python syntax or converter helper namespace')
                if v['domain'] not in ('real', 'complex', 'positive_real', 'nonnegative_real'):
                    raise ValueError('explicit supported variable domain required')
                _text(v['units'], 'variable units')
                if type(v['dimension_GeV']) is not int or not -32 <= v['dimension_GeV'] <= 32:
                    raise ValueError('explicit variable dimension required')
            if len(set(names)) != len(names):
                raise ValueError('duplicate variable')
            if type(r['points']) is not list or len(r['points']) > 256:
                raise ValueError('bounded complete optional numerical point list required')
            point_ids = set()
            for point in r['points']:
                custody._keys(point, ('id', 'values'), 'numerical point')
                if _id(point['id']) in point_ids:
                    raise ValueError('duplicate point')
                point_ids.add(point['id'])
                custody._keys(point['values'], names, 'complete numerical coordinates')
                for v in r['variables']:
                    z = _pair(point['values'][v['name']])
                    if (v['domain'] != 'complex' and z.imag != 0
                            or v['domain'] == 'positive_real' and z.real <= 0
                            or v['domain'] == 'nonnegative_real' and z.real < 0):
                        raise ValueError('point violates its declared variable domain')
    if c['schema_version'] == 2:
        for script in c['scripts']:
            process = feynarts_amplitude.process(script['feynarts_process'])
            if len(script['results']) != 1 or script['results'][0]['id'] != process['id'] or script['results'][0]['symbol'] != 'ravelAmplitude' or script['results'][0]['representation'] != 'feyncalc_tensor' or script['results'][0]['points']:
                raise ValueError('complete native amplitude tensor result required; no guessed scalar numerical reduction')
            if script['markers'] != {'symbolic':[process['id']], 'numerical':[], 'latex':[process['id']], 'status':'complete'}:
                raise ValueError('source-defined amplitude marker population required')
    return c


def _load(task, base):
    validate(task)
    path = custody._pin({'path': task['input'], 'sha256': task['input_sha256']}, base)
    return path, validate_config(document(path))


def inputs(task, base):
    path, c = _load(task, base)
    files = [path]
    for key in ('original_task', 'kernel', 'application_metadata'):
        files.append(custody._pin(c[key], path.parent))
    if not os.access(files[-2], os.X_OK):
        raise ValueError('kernel must be an explicitly supplied executable')
    trees = {}
    for key in ('provider_tree', 'script_tree'):
        trees[key], manifest, members = custody._tree(c[key], path.parent)
        files += [manifest, *members]
    if not (trees['provider_tree']/c['provider_entry']).is_file():
        raise ValueError('declared provider entry missing')
    for s in c['scripts']:
        p = custody._pin({'path': s['relative_path'], 'sha256': s['sha256']}, trees['script_tree'])
        if not p.is_relative_to(trees['script_tree']):
            raise ValueError('script escapes declared source tree')
    if c['schema_version'] == 2:
        from ravel.physics import feynarts_amplitude, feyn_graph
        _, _, addon_files = feynarts_amplitude.source_inputs(c['feynarts'], path.parent)
        files += addon_files + [feyn_graph.API]
        api = document(feyn_graph.API)['feynarts']
        for rel, sha in api['feyncalc_required_sources'].items():
            if custody._hash(trees['provider_tree']/rel) != sha:
                raise ValueError('actual FeynCalc package API source differs')
        for script in c['scripts']:
            if (trees['script_tree']/script['relative_path']).read_text() != feynarts_amplitude.script(script['feynarts_process']):
                raise ValueError('amplitude source script differs from complete typed process')
    files += [custody._pin(pin, path.parent) for pin in c['backend_files'].values()]
    py = custody._pin(c['python_runtime']['python'], path.parent)
    if not os.access(py, os.X_OK):
        raise ValueError('conversion Python must be executable')
    files.append(py)
    for key in ('sympy_tree', 'mpmath_tree'):
        root, manifest, members = custody._tree(c['python_runtime'][key], path.parent)
        if not (root/'__init__.py').is_file():
            raise ValueError('complete supplied symbolic dependency package required')
        files += [manifest, *members]
    files += list(Path(__file__).resolve().parents[1].rglob('*.py'))
    return sorted(set(files))


def context_inputs(task,base):
    inputs(task,base);p,c=_load(task,base)
    files=[p,Path(__file__),custody._pin(c['original_task'],p.parent),custody._pin(c['kernel'],p.parent),custody._pin(c['application_metadata'],p.parent),custody._pin(c['python_runtime']['python'],p.parent)]
    files += [custody._pin(c[k]['manifest'],p.parent) for k in ('provider_tree','script_tree')]
    files += [custody._pin(c['python_runtime'][k]['manifest'],p.parent) for k in ('sympy_tree','mpmath_tree')]
    files += [custody._pin(pin,p.parent) for pin in c['backend_files'].values()]
    if c['schema_version']==2:
        from ravel.physics import feyn_graph
        files += [feyn_graph.API,custody._pin(c['feynarts']['tree']['manifest'],p.parent),custody._pin(c['feynarts']['model_tree']['manifest'],p.parent),custody._pin(c['feynarts']['patched_source_receipt'],p.parent)]
    return sorted(set(files))


def execution_seconds(task, base):
    return _load(task, base)[1]['max_seconds']


def _approved(task, output, expected_mode='symbolic-evaluation'):
    from ravel.workflow import science
    out = Path(output).absolute()
    for rd in (out, *out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            selected = science.verify_worker(rd)
            spec = science.execution_spec(rd)
            if (spec['mode'] != expected_mode or spec['task'] != task
                    or out.resolve() != (rd/selected['output_directory']).resolve()):
                raise ValueError('symbolic worker differs from approved task/output')
            return rd, selected
    raise ValueError('symbolic execution requires its approved supervised worker')


def wrapper_script(c, s, provider, script, sidecar, addon_root=None, model_root=None):
    """Explicit transport adaptation; source script and original prints unchanged."""
    q = lambda x: json.dumps(str(x), ensure_ascii=False)
    rows = ',\n'.join('<|"id"->'+q(r['id'])+',"symbol"->'+q(r['symbol'])+
        ',"defined"->ValueQ['+r['symbol']+'],"formula"->ToString['+r['symbol']+
        ',InputForm,PageWidth->Infinity]|>' for r in s['results'])
    addon_setup = '$LoadAddOns={};\n'
    extra = ''
    addon_observation = ''
    if c['schema_version'] == 2:
        addon_setup = '$LoadAddOns={"FeynArts"};\n$FAPatch=False;\nFeynCalc`$FeynArtsDirectory='+q(addon_root)+';\n'
        addon_observation = 'ravelFADirectoryBefore=FeynArts`$FeynArtsDir;\n'
        extra = 'FeynArts`$ModelPath={'+q(model_root)+'};\nravelClassesModel='+q(c['feynarts']['classes_model'])+';\nravelGenericModel='+q(c['feynarts']['generic_model'])+';\nravelDiagramPDF='+q(Path(sidecar).parent/'diagrams.pdf')+';\n'
    return ('$HistoryLength=0;\n$FeynCalcStartupMessages=False;\n'+addon_setup+
        '$Parallelize=False;\n'
        '$Path={'+q(Path(provider)/'FeynCalc')+',FileNameJoin[{$InstallationDirectory,"SystemFiles","Kernel","Packages"}]};\n'
        'ravelProvider='+q(Path(provider)/c['provider_entry'])+';\n'
        'ravelBefore=FindFile["FeynCalc`"];\n'
        'ravelLoaded=CheckAbort[Check[Get[ravelProvider];True,False],False];\n'
        'ravelProviderVersion=ToString['+c['provider_version_symbol']+'];\n'
        +addon_observation+extra+'ravelScriptOK=CheckAbort[Check[Get['+q(script)+'];True,False],False];\n'
        'ravelAfter=FindFile["FeynCalc`"];\n'
        'ravelRows={'+rows+'};\n'
        'ravelReceipt=<|"schema_version"->1,"script_id"->'+q(s['id'])+
        ',"kernel_version"->$VersionNumber,"kernel_version_string"->$Version,'
        '"process_id"->$ProcessID,"provider_loaded"->TrueQ[ravelLoaded],'
        '"provider_before"->ravelBefore,"provider_after"->ravelAfter,'
        '"provider_version"->ravelProviderVersion,"script_ok"->TrueQ[ravelScriptOK],'
        '"parallel_kernel_count"->Length[Kernels[]],"results"->ravelRows'+(',"feynarts"-><|"version"->ToString[FeynArts`$FeynArtsVersion],"configured_directory"->FeynCalc`$FeynArtsDirectory,"directory_before"->ravelFADirectoryBefore,"directory"->FeynArts`$FeynArtsDir,"model_path"->FeynArts`$ModelPath,"records"->ravelFARecords|>' if c['schema_version']==2 else '')+'|>;\n'
        'Export['+q(sidecar)+',ravelReceipt,"RawJSON"];\n')


def marker_census(stdout, expected):
    """Count marker identities; canonical formulas come from the separate sidecar."""
    rows = {k: [] for k in ('symbolic', 'numerical', 'latex', 'status')}
    kinds = {'SYMBOLIC_RESULT': 'symbolic', 'NUMERICAL_RESULT': 'numerical', 'LATEX_RESULT': 'latex'}
    malformed = []
    for line in stdout.splitlines():
        line = line.strip()
        m = re.match(r'^(SYMBOLIC_RESULT|NUMERICAL_RESULT|LATEX_RESULT)\[([^\]]+)\]:', line)
        if m:
            rows[kinds[m[1]]].append(m[2])
        elif line.startswith('STATUS:'):
            rows['status'].append(line.partition(':')[2].strip())
        elif any(line.startswith(x) for x in kinds):
            malformed.append(line)
    valid = not malformed and rows['status'] == [expected['status']]
    valid = valid and all(sorted(rows[k]) == sorted(expected[k]) for k in kinds.values())
    return {'valid': valid, 'observed': rows, 'malformed': malformed,
            'canonical_formula_source': 'owned_inputform_sidecar', 'original_multiline_text_retained': True}


def validate_sidecar(receipt, c, script, provider, native_pid):
    custody._keys(receipt, ('schema_version', 'script_id', 'kernel_version', 'kernel_version_string',
        'process_id', 'provider_loaded', 'provider_before', 'provider_after', 'provider_version',
        'script_ok', 'parallel_kernel_count', 'results', *(['feynarts'] if c['schema_version']==2 else [])), 'canonical symbolic sidecar')
    expected_path = str(Path(provider)/c['provider_entry'])
    if (receipt['schema_version'] != 1 or receipt['script_id'] != script['id']
            or receipt['kernel_version'] != c['expected_kernel_version']
            or type(receipt['process_id']) is not int or receipt['process_id'] != native_pid
            or receipt['provider_loaded'] is not True or receipt['script_ok'] is not True
            or receipt['provider_before'] != expected_path or receipt['provider_after'] != expected_path
            or receipt['provider_version'] != c['expected_provider_version']
            or type(receipt['parallel_kernel_count']) is not int or receipt['parallel_kernel_count'] != 0):
        raise ValueError('kernel/provider/script identity or evaluated postconditions failed')
    if type(receipt['results']) is not list or len(receipt['results']) != len(script['results']):
        raise ValueError('incomplete canonical result roster')
    for row, declared in zip(receipt['results'], script['results']):
        custody._keys(row, ('id', 'symbol', 'defined', 'formula'), 'canonical result')
        if row['id'] != declared['id'] or row['symbol'] != declared['symbol'] or row['defined'] is not True:
            raise ValueError('result symbol/identity/definition differs')
        formula = _text(row['formula'], 'canonical InputForm formula', 4*1024**2)
        if re.search(r'\$(?:Failed|Aborted)|\b(?:Indeterminate|ComplexInfinity|DirectedInfinity|Integrate|NIntegrate|DSolve|NDSolve)\b', formula):
            raise ValueError('failed/nonfinite or residual requested computation in formula')
    if c['schema_version'] == 2:
        a=receipt['feynarts']
        custody._keys(a, ('version','configured_directory','directory_before','directory','model_path','records'), 'native amplitude provenance')
        expected_addon=Path(provider).parent/'feynarts'
        directories=[a[k] for k in ('configured_directory','directory_before','directory')]
        if a['version'] != 'FeynArts 3.12 (27 Mar 2025)' or any(type(value) is not str or not Path(value).is_absolute() or Path(value)!=expected_addon for value in directories) or a['model_path'] != [str(Path(provider).parent/'models')]:
            raise ValueError('actual FeynArts version/component/model resolution differs')
        records=a['records']; custody._keys(records, ('diagram_count','topologies','insertions','original_amplitudes','converted_amplitudes'), 'full native amplitudes')
        count=records['diagram_count']
        if type(count) is not int or not 0<=count<=script['feynarts_process']['max_diagrams'] or type(records['converted_amplitudes']) is not list or len(records['converted_amplitudes']) != count:
            raise ValueError('complete native amplitude population differs')
        for value in [records['topologies'],records['insertions'],records['original_amplitudes'],*records['converted_amplitudes']]:_text(value,'complete InputForm native population',16*1024**2)
    return receipt['results']


def convert_result(row, declaration, converter):
    """Original converter APIs; explicit complex pairs, exact free-variable census."""
    formula = row['formula']
    names = [v['name'] for v in declaration['variables']]
    expr = converter.mathematica_to_sympy(formula)
    if {str(s) for s in expr.free_symbols} != set(names):
        raise ValueError('declared variables differ from the complete formula free symbols')
    source = converter.mathematica_to_python_source(formula, names,
        function_name='result_'+declaration['id'], dimension_comment=False)
    try:
        tree = ast.parse(source)
    except (SyntaxError, TypeError, ValueError) as exc:
        raise ValueError('generated Python is not valid source') from exc
    functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if (len(functions) != 1 or not isinstance(functions[0], ast.FunctionDef)
            or functions[0].name != 'result_'+declaration['id']
            or [a.arg for a in functions[0].args.args] != names
            or functions[0].args.posonlyargs or functions[0].args.kwonlyargs
            or functions[0].args.vararg or functions[0].args.kwarg or functions[0].args.defaults
            or len(functions[0].body) != 1 or not isinstance(functions[0].body[0], ast.Return)):
        raise ValueError('generated Python lacks its exact declared function/coordinate signature')
    compile(tree, '<source-bound-symbolic-function>', 'exec', dont_inherit=True)
    fn = converter.mathematica_to_callable(formula, names) if declaration['points'] else None
    values = []
    for point in declaration['points']:
        args = [_pair(point['values'][name]) for name in names]
        args = [z.real if z.imag == 0 else z for z in args]
        try:
            value = fn(*args)
            if type(value) is bool:
                raise ValueError('boolean cannot become a numerical physics value')
            z = complex(value)
            _number(z.real); _number(z.imag)
            values.append({'id': point['id'], 'values': deepcopy(point['values']),
                           'status': 'delivered', 'real': z.real, 'imag': z.imag})
        except Exception as exc:
            values.append({'id': point['id'], 'values': deepcopy(point['values']),
                           'status': 'failed', 'error': type(exc).__name__+': '+str(exc),
                           'real': None, 'imag': None})
    return {'id': row['id'], 'symbol': row['symbol'], 'formula': formula,
        'status': 'delivered' if all(p['status'] == 'delivered' for p in values) else 'failed',
        'symbolic_status': 'delivered', 'conversion_status': 'delivered',
        'numerical_status': ('not_requested' if not values else
            'delivered' if all(p['status'] == 'delivered' for p in values) else 'failed'),
        'variables': deepcopy(declaration['variables']), 'units': declaration['units'],
        'dimension_GeV': declaration['dimension_GeV'], 'conventions': declaration['conventions'],
        'assumptions': deepcopy(declaration['assumptions']), 'python_source': source,
        'points': values, 'physics_validated': False}


def _external_module(path, name, expected):
    observation = document_pin(path)
    if observation['sha256'] != expected:
        raise ValueError('captured external module changed')
    module = ModuleType(name); module.__file__ = str(path)
    previous = sys.modules.get(name); sys.modules[name] = module
    try:
        exec(compile(observation['text'], str(path), 'exec'), module.__dict__)
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
    return module


def _write(path, value):
    path = Path(path)
    raw = (json.dumps(value, indent=2, allow_nan=False)+'\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _write_text(path, text):
    raw = text.encode('utf-8')
    with Path(path).open('xb') as stream:
        stream.write(raw)
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw)}


def _strict_json(text):
    from ravel.workflow.state_io import _unique
    def invalid(value):
        raise ValueError('nonfinite canonical JSON: '+value)
    def floating(value):
        result = float(value)
        if not math.isfinite(result): invalid(value)
        return result
    return json.loads(text, object_pairs_hook=_unique, parse_constant=invalid, parse_float=floating)


def _conversion_runtime(c, base):
    """Verify actual interpreter and package origins before source conversion."""
    py = custody._pin(c['python_runtime']['python'], base)
    if custody._hash(Path(sys.executable).resolve()) != custody._hash(py):
        raise ValueError('actual worker Python differs from declared conversion runtime')
    import importlib.util
    if any(name == root or name.startswith(root+'.') for name in sys.modules for root in ('sympy', 'mpmath')):
        raise ValueError('conversion requires fresh optional modules in its approved worker')
    roots = {}
    for name in ('sympy', 'mpmath'):
        root, _, _ = custody._tree(c['python_runtime'][name+'_tree'], base)
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None or Path(spec.origin).resolve() != (root/'__init__.py').resolve():
            raise ValueError('actual symbolic dependency origin differs: '+name)
        roots[name] = root
    # These imports happen exclusively inside the approved worker after origin checks.
    import sympy
    import mpmath
    for name, module in (('sympy', sympy), ('mpmath', mpmath)):
        if Path(module.__file__).resolve() != (roots[name]/'__init__.py').resolve():
            raise ValueError('loaded symbolic dependency origin differs: '+name)
    return roots


class _Delivery(dict):
    """Carry original in-memory commitments through the common worker/report tail."""


def _members(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('symbolic output contains an alias')
        if path.is_file():
            result[path.relative_to(root).as_posix()] = custody._hash(path)
        elif not path.is_dir():
            raise ValueError('nonordinary symbolic output')
    return result


def _report(result):
    lines = ['# Declared symbolic batch', '',
        ('Source-bound FeynArts/FeynCalc tensor amplitude delivery; scalar reduction and numerical equivalence remain unqualified.' if result.get('status_scope')=='source_bound_feynarts_amplitude_delivery' else 'Source-bound formula and Python delivery. Physics validity and numerical equivalence remain unqualified.'), '',
        'Every requested result is retained, including failed and unattempted entries.', '']
    for row in result['results']:
        lines += ['## '+row['id'], '', 'Status: '+row['status']+'.', '']
        if row.get('formula') is not None:
            lines += ['Canonical InputForm:', '', '```text', row['formula'], '```', '']
        for field in ('units', 'conventions'):
            if field in row:
                lines += [field.capitalize()+': '+row[field], '']
        for point in row['points']:
            lines += [point['id']+': '+point['status']+
                ('; real='+str(point['real'])+', imaginary='+str(point['imag'])
                 if point['status'] == 'delivered' else ''), '']
        if 'error' in row:
            lines += ['Delivery error: '+row['error'], '']
    return '\n'.join(lines)+'\n'


def write_report(result, output):
    out = Path(output)
    with (out/'symbolic-report.md').open('x') as stream:
        stream.write(_report(result))
    native_figures=[str(Path(s['rendered_pdf']['path']).relative_to(out)) for s in result['scripts'] if 'rendered_pdf' in s]
    return [{'stem': 'symbolic-report', 'files': ['symbolic-report.md', 'symbolic-evaluation.json',*native_figures],
        'normalization': 'No numerical rescaling or omission; complete declared result roster.'}]


def finalize(result, output):
    """Common worker result/report publication must preserve the delivered batch."""
    if not isinstance(result, _Delivery) or dict(result) != result.expected:
        raise ValueError('returned symbolic delivery changed before publication')
    out = Path(output)
    if out.resolve() != result.output or out.stat().st_ino != result.output_inode:
        raise ValueError('symbolic output directory changed')
    if document(out/'result.json') != result.expected or document(out/'symbolic-evaluation.json') != result.expected:
        raise ValueError('common and adapter result bytes/values diverged')
    if (out/'symbolic-report.md').read_text() != _report(result.expected):
        raise ValueError('complete symbolic report changed')
    observed = _members(out)
    common = {'result.json', 'figures.json', 'recipe.json', 'verification.json',
              'checkin2.json', 'RESULT.md', 'symbolic-report.md'}
    if set(observed) != set(result.emitted) | common or any(observed.get(k) != v for k, v in result.emitted.items()):
        raise ValueError('symbolic emitted membership or original bytes changed')
    if result.inputs_before != {str(p): custody._hash(p) for p in inputs(result.task, result.base)}:
        raise ValueError('symbolic inputs changed during common publication')
    if sum((out/p).stat().st_size for p in observed) > result.max_output_bytes:
        raise ValueError('complete published symbolic artifacts exceed byte bound')


def run(task, base, output):
    path, c = _load(task, base)
    rd, selected = _approved(task, output, 'feynarts-amplitude' if c['schema_version']==2 else 'symbolic-evaluation')
    if c['max_seconds'] > selected['max_seconds']:
        raise ValueError('symbolic aggregate deadline exceeds approved stage')
    start = time.monotonic()
    files = inputs(task, base)
    before = {str(p): custody._hash(p) for p in files}
    out = Path(output).resolve(); out.mkdir(parents=True, exist_ok=True)
    work = rd/'work/symbolic-evaluation'/out.name
    if work.exists() or any(x.is_symlink() for x in (work, *work.parents)):
        raise ValueError('fresh regular symbolic workspace required')
    if any(out == p or out.is_relative_to(p) or p.is_relative_to(out) for p in files):
        raise ValueError('output overlaps supplied input')
    work.mkdir(parents=True)
    custody._copy(c['provider_tree'], path.parent, work/'provider')
    custody._copy(c['script_tree'], path.parent, work/'scripts')
    if c['schema_version'] == 2:
        custody._copy(c['feynarts']['tree'], path.parent, work/'feynarts')
        custody._copy(c['feynarts']['model_tree'], path.parent, work/'models')
    staged = {key: custody.source_tree(work/key) for key in (('provider','scripts','feynarts','models') if c['schema_version']==2 else ('provider','scripts'))}
    original = {name: custody._pin(pin, path.parent) for name, pin in c['backend_files'].items()}
    expected_artifacts = {}
    def remember(pin):
        relative = Path(pin['path']).relative_to(out).as_posix()
        if relative in expected_artifacts:
            raise ValueError('refuse replacement of an already committed symbolic artifact')
        expected_artifacts[relative] = pin['sha256']
        return pin
    def emit_json(destination, value):
        return remember(_write(destination, value))
    def emit_text(destination, text):
        return remember(_write_text(destination, text))
    def verify_emitted(*, capture_native=False):
        observed = _members(out)
        if any(observed.get(k) != value for k, value in expected_artifacts.items()):
            raise ValueError('previously committed symbolic artifact changed')
        if capture_native:
            expected_artifacts.update({k:v for k,v in observed.items() if k not in expected_artifacts})
        elif observed != expected_artifacts:
            raise ValueError('unissued symbolic artifact appeared outside the native phase')
    def captured(path):
        observation = document_pin(path)
        if expected_artifacts.get(Path(path).relative_to(out).as_posix()) != observation['sha256']:
            raise ValueError('native artifact changed before its actual consumption')
        return observation
    emit_json(out/'operation-input.json', {'task': task, 'configuration': c, 'inputs': before})
    rows = []
    for script in c['scripts']:
        for r in script['results']:
            rows.append({'id': r['id'], 'script_id': script['id'], 'status': 'unattempted',
                'symbolic_status': 'unattempted', 'conversion_status': 'unattempted',
                'numerical_status': 'unattempted' if r['points'] else 'not_requested',
                'formula': None, 'points': [{'id': p['id'], 'status': 'unattempted'} for p in r['points']]})
    result = _Delivery({'status': 'failed', 'status_scope': ('source_bound_feynarts_amplitude_delivery' if c['schema_version']==2 else SCOPE), 'physics_validated': False,
        'original_task_complete': False, 'backend_revision': REVISION,
        'transport': 'direct_fresh_kernel_plus_owned_InputForm_sidecar',
        'results': rows, 'scripts': [{'id': s['id'], 'status': 'unattempted',
            'results': [r['id'] for r in s['results']]} for s in c['scripts']],
        'expected_result_ids': [r['id'] for r in rows],
        'numerical_equivalence_qualified': False, 'source': c['source'], 'generated_events': 0,
        'limitations': ['Symbolic computation and conversion do not establish formula, basis, gauge or SM correctness.',
            'Supplied physical conventions and dimensions are retained, not inferred or certified.',
            'An existing licensed kernel is required; no installation, activation or configuration edits.',
            'Native output byte bound is checked at phase boundaries, not an operating-system disk quota.',
            'Installed proprietary libraries and standard library/OS are outside the finite source capsule.']})
    previous_prefix, previous_write = sys.pycache_prefix, sys.dont_write_bytecode
    cache = work/'empty-bytecode-cache'; cache.mkdir()
    sys.pycache_prefix, sys.dont_write_bytecode = str(cache), True
    try:
        _conversion_runtime(c, path.parent)
        parser = _external_module(original['wolfram_runner.py'], '_ravel_heptapod_parser', BACKEND['wolfram_runner.py'])
        converter = _external_module(original['symbolic_to_python.py'], '_ravel_heptapod_converter', BACKEND['symbolic_to_python.py'])
        from ravel.physics.reinterpret_db import execute_native
        for s in c['scripts']:
            remaining = c['max_seconds']-(time.monotonic()-start)
            if remaining <= 0:
                raise ValueError('aggregate symbolic deadline exhausted before next script')
            sub = out/s['id']; sub.mkdir()
            sidecar = sub/'canonical-symbolic.json'
            wl = sub/'wrapper.wl'
            emit_text(wl, wrapper_script(c, s, work/'provider', work/'scripts'/s['relative_path'], sidecar, work/'feynarts', work/'models'))
            emit_json(sub/'attempt.json', {'id': s['id'], 'status': 'started', 'result_ids': [r['id'] for r in s['results']]})
            script_record = next(row for row in result['scripts'] if row['id'] == s['id'])
            script_record['status'] = 'attempted_unresolved'
            for row in rows:
                if row['script_id'] == s['id']:
                    row['status'] = 'attempted_unresolved'
            overrides = {key: os.environ.pop(key) for key in INIT_ENVIRONMENT if key in os.environ}
            try:
                native = execute_native([str(custody._pin(c['kernel'], path.parent)), '-noinit', '-noprompt', '-script', str(wl)],
                    sub, dict(c, max_seconds=remaining))
            finally:
                os.environ.update(overrides)
                verify_emitted(capture_native=True)
            emitted = [p for p in out.rglob('*') if p.is_file()]
            if any(p.is_symlink() for p in out.rglob('*')) or sum(p.stat().st_size for p in emitted) > c['max_output_bytes']:
                raise ValueError('complete symbolic output exceeds declared byte budget or contains aliases')
            stdout = captured(sub/'native-stdout.log')['text']
            parsed = parser._parse_structured_output(stdout)
            emit_json(sub/'upstream-parsed.json', parsed)
            markers = marker_census(stdout, s['markers'])
            emit_json(sub/'marker-census.json', markers)
            if not markers['valid']:
                raise ValueError('original marker population missing, duplicated or malformed')
            process = _strict_json(captured(sub/'native-process.json')['text'])
            canonical_observation = captured(sidecar)
            canonical_snapshot = emit_text(sub/'canonical-captured.json', canonical_observation['text'])
            canonical = validate_sidecar(_strict_json(canonical_observation['text']), c, s, work/'provider', process['pid'])
            script_rows = []
            for row, declared in zip(canonical, s['results']):
                try:
                    if c['schema_version']==2 and declared['representation']=='feyncalc_tensor':
                        converted = {'id':row['id'],'symbol':row['symbol'],'formula':row['formula'],'status':'delivered','symbolic_status':'delivered','conversion_status':'not_requested_tensor','numerical_status':'not_requested','representation':'feyncalc_tensor','variables':deepcopy(declared['variables']),'units':declared['units'],'dimension_GeV':declared['dimension_GeV'],'conventions':declared['conventions'],'assumptions':deepcopy(declared['assumptions']),'points':[],'physics_validated':False,'scalar_reduction_qualified':False}
                    else:
                        converted = convert_result(row, declared, converter)
                        source = converted.pop('python_source')
                        code = sub/(declared['id']+'.py')
                        converted['python_source'] = emit_text(code, source)
                    converted['canonical_source'] = canonical_snapshot
                    converted['original_canonical_source'] = {k:canonical_observation[k] for k in ('path','sha256')}
                except Exception as exc:
                    converted = {'id': declared['id'], 'symbol': declared['symbol'], 'status': 'failed',
                        'symbolic_status': 'delivered', 'conversion_status': 'failed',
                        'numerical_status': 'unattempted' if declared['points'] else 'not_requested',
                        'formula': row['formula'], 'error': type(exc).__name__+': '+str(exc),
                        'points': [{'id': p['id'], 'status': 'unattempted'} for p in declared['points']]}
                converted['script_id'] = s['id']
                rows[result['expected_result_ids'].index(converted['id'])] = converted
                script_rows.append(converted['id'])
            verify_emitted()
            if c['schema_version']==2:
                script_record['feynarts']=_strict_json(canonical_observation['text'])['feynarts']
                if s['feynarts_process']['render_pdf']:
                    pdf=sub/'diagrams.pdf'
                    if not pdf.is_file() or pdf.stat().st_size==0 or not pdf.read_bytes().startswith(b'%PDF-'):
                        raise ValueError('requested actual native diagram PDF missing')
                    script_record['rendered_pdf']={'path':str(pdf),'sha256':expected_artifacts[pdf.relative_to(out).as_posix()],'size':pdf.stat().st_size}
            script_record.update(native=native, results=script_rows,
                status='delivered' if all(r['status'] == 'delivered' for r in rows if r['script_id'] == s['id']) else 'failed')
            emit_json(sub/'delivery.json', {'rows': [r for r in rows if r['script_id'] == s['id']]})
        if before != {str(p): custody._hash(p) for p in inputs(task, base)}:
            raise ValueError('symbolic source/runtime custody changed')
        if any(custody.source_tree(work/key) != value for key, value in staged.items()):
            raise ValueError('staged provider/script source changed during evaluation')
        if time.monotonic()-start > c['max_seconds']:
            raise ValueError('aggregate deadline exhausted during conversion or ending custody')
        result['status'] = 'passed' if all(r['status'] == 'delivered' for r in rows) else 'failed'
    except Exception as exc:
        result['failure'] = type(exc).__name__+': '+str(exc)
    finally:
        sys.pycache_prefix, sys.dont_write_bytecode = previous_prefix, previous_write
    result['elapsed_seconds'] = time.monotonic()-start
    result['delivered_results'] = sum(r['status'] == 'delivered' for r in rows)
    emit_json(out/'symbolic-evaluation.json', result)
    result.expected = deepcopy(dict(result))
    result.output, result.output_inode = out, out.stat().st_ino
    result.task, result.base = deepcopy(task), Path(base)
    result.inputs_before = before
    result.emitted = dict(expected_artifacts)
    result.max_output_bytes = c['max_output_bytes']
    if sum((out/p).stat().st_size for p in result.emitted) > c['max_output_bytes']:
        raise ValueError('complete symbolic delivery exceeds byte bound')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('inspect',))
    parser.add_argument('--input', required=True); parser.add_argument('--input-sha256', required=True)
    args = parser.parse_args(argv)
    task = {'input': args.input, 'input_sha256': args.input_sha256}
    path, c = _load(task, Path.cwd()); paths = inputs(task, Path.cwd())
    print(json.dumps({'mode': 'symbolic-evaluation', 'source': c['source'],
        'input': str(path), 'input_files': len(paths), 'scripts': len(c['scripts']),
        'results': sum(len(s['results']) for s in c['scripts']), 'execution_authorized': False,
        'next': 'Use this task in an ordinary schema2 science plan and its review policy.'}, indent=2))
    return 0
