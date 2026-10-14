"""Synthetic transport/control cases. No CAS, native provider or scientific data."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ravel.physics import symbolic_evaluation as se
from ravel.workflow import scientific_context as sc, scientific_report, science


def pin(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path.write_text(value if type(value) is str else json.dumps(value)+'\n')
    return pin(path)


def result_decl(identity='width', variables=None):
    return {'id': identity, 'symbol': identity, 'variables': variables or [], 'units': 'GeV',
        'dimension_GeV': 1, 'conventions': 'Synthetic constant fixture; no physical vertex asserted.',
        'assumptions': ['No numerical physics qualification.'], 'points': [{'id': 'constant', 'values': {}}]}


def configuration(base, monkeypatch, scripts=1):
    base.mkdir(exist_ok=True)
    def tree(name, entries):
        root = base/name; root.mkdir()
        for key, raw in entries.items():
            f = root/key; f.parent.mkdir(parents=True, exist_ok=True); f.write_text(raw)
        manifest = base/(name+'-manifest.json'); save(manifest, se.custody.source_tree(root))
        return {'root': str(root), 'manifest': pin(manifest)}
    backend = {}
    for name in se.BACKEND:
        f = base/name; f.write_text('# Inert synthetic backend member '+name+'\n'); backend[name] = pin(f)
    monkeypatch.setattr(se, 'BACKEND', {k: v['sha256'] for k,v in backend.items()})
    kernel = base/'kernel'; kernel.write_text('inert source fixture'); kernel.chmod(0o700)
    metadata = save(base/'metadata.txt', 'Synthetic runtime metadata')
    original = save(base/'original.txt', 'Original complete multi-family scientific task remains unresolved.')
    source = tree('scripts', {'script'+str(i)+'.wl': 'Print["SYMBOLIC_RESULT[width]: 0"];\n' for i in range(scripts)})
    c = {'schema_version': 1, 'backend_revision': se.REVISION, 'source': 'Explicit inert engineering fixture',
        'original_task': original, 'trusted_executable_sources': True, 'kernel': pin(kernel),
        'application_metadata': metadata, 'provider_tree': tree('provider', {'FeynCalc/FeynCalc.m': 'inert source'}),
        'provider_entry': 'FeynCalc/FeynCalc.m', 'provider_version_symbol': '$FeynCalcVersion',
        'expected_provider_version': 'fixture', 'expected_kernel_version': 15.0, 'script_tree': source,
        'backend_files': backend, 'python_runtime': {'python': pin(kernel),
            'sympy_tree': tree('sympy', {'__init__.py': '# fake'}),
            'mpmath_tree': tree('mpmath', {'__init__.py': '# fake'})},
        'scripts': [], 'max_seconds': 40, 'max_ram_mib': 1024, 'max_output_bytes': 1024*1024}
    for i in range(scripts):
        r = result_decl('width'+str(i))
        c['scripts'].append({'id': 'script'+str(i), 'relative_path': 'script'+str(i)+'.wl',
            'sha256': pin(Path(source['root'])/('script'+str(i)+'.wl'))['sha256'],
            'markers': {'symbolic': [r['id']], 'numerical': [], 'latex': [], 'status': 'complete'},
            'results': [r]})
    path = base/'request.json'; save(path,c)
    task = {'input': str(path), 'input_sha256': pin(path)['sha256']}
    return c, task


def sidecar(c, script, provider, formula='0'):
    return {'schema_version': 1, 'script_id': script['id'], 'kernel_version': 15.0,
        'kernel_version_string': 'explicit inert control', 'process_id': 123,
        'provider_loaded': True, 'provider_before': str(provider/'FeynCalc/FeynCalc.m'),
        'provider_after': str(provider/'FeynCalc/FeynCalc.m'), 'provider_version': 'fixture',
        'script_ok': True, 'parallel_kernel_count': 0,
        'results': [{'id': r['id'], 'symbol': r['symbol'], 'defined': True, 'formula': formula}
                    for r in script['results']]}


class Converter:
    """An inert API double; cannot establish upstream conversion correctness."""
    def __init__(self, symbols=(), value=0):
        self.symbols, self.value, self.calls = symbols, value, []
    def mathematica_to_sympy(self, expr):
        self.calls.append(('parse', expr)); return SimpleNamespace(free_symbols=set(self.symbols))
    def mathematica_to_python_source(self, expr, names, **kwargs):
        self.calls.append(('source', expr, names, kwargs)); return 'def '+kwargs['function_name']+'('+','.join(names)+'):\n    return 0\n'
    def mathematica_to_callable(self, expr, names):
        self.calls.append(('callable', expr, names))
        def f(*args):
            self.calls.append(('evaluate', args))
            if isinstance(self.value, Exception): raise self.value
            return self.value
        return f


def test_constant_and_complex_lower_api_transport():
    d = result_decl(); converter = Converter(value=0)
    r = se.convert_result({'id': 'width', 'symbol': 'width', 'formula': '0'}, d, converter)
    assert r['status'] == 'delivered' and r['points'][0]['real'] == 0 and r['points'][0]['imag'] == 0
    assert ('callable', '0', []) in converter.calls
    d['variables'] = [{'name': 'g', 'domain': 'complex', 'units': '1', 'dimension_GeV': 0}]
    d['points'] = [{'id': 'complex', 'values': {'g': {'real': 1, 'imag': 2}}}]
    converter = Converter(symbols=['g'], value=3+4j)
    r = se.convert_result({'id': 'width', 'symbol': 'width', 'formula': 'g'}, d, converter)
    assert ('evaluate', (1+2j,)) in converter.calls
    assert (r['points'][0]['real'], r['points'][0]['imag']) == (3, 4)
    assert not r['physics_validated']


def test_omitted_free_symbol_and_numeric_failure_preserve_scope():
    d = result_decl()
    with pytest.raises(ValueError, match='free symbols'):
        se.convert_result({'id': 'width', 'symbol': 'width', 'formula': 'g'},d,Converter(symbols=['g']))
    r = se.convert_result({'id': 'width', 'symbol': 'width', 'formula': '0'},d,Converter(value=ValueError('domain')))
    assert r['symbolic_status'] == r['conversion_status'] == 'delivered'
    assert r['status'] == r['numerical_status'] == 'failed' and r['points'][0]['real'] is None


def test_multiline_original_marker_is_separate_from_canonical_formula():
    expected = {'symbolic': ['width'], 'numerical': [], 'latex': [], 'status': 'complete'}
    stdout = 'SYMBOLIC_RESULT[width]: long expression\n  continues here\nSTATUS: complete\n'
    assert se.marker_census(stdout, expected)['valid']
    for changed in (stdout+'SYMBOLIC_RESULT[width]: again\n', stdout.replace('[width]', '[wrong]'),
                    stdout.replace('STATUS: complete', ''), stdout+'SYMBOLIC_RESULT[malformed\n'):
        assert not se.marker_census(changed, expected)['valid']


@pytest.mark.parametrize('field,value', [('provider_after', '/ambient/FeynCalc.m'), ('process_id', 999),
    ('provider_loaded', False), ('script_ok', False), ('parallel_kernel_count', 1), ('provider_version', 'unknown')])
def test_sidecar_runtime_identity_failure(tmp_path, monkeypatch, field, value):
    c,_ = configuration(tmp_path,monkeypatch); s=c['scripts'][0]; p=tmp_path/'staged'
    receipt=sidecar(c,s,p);receipt[field]=value
    with pytest.raises(ValueError):se.validate_sidecar(receipt,c,s,p,123)


def test_wrapper_and_complete_sidecar(tmp_path,monkeypatch):
    c,_=configuration(tmp_path,monkeypatch);s=c['scripts'][0];p=tmp_path/'staged'
    wl=se.wrapper_script(c,s,p,tmp_path/'unchanged.wl',tmp_path/'output.json')
    assert '$UserBaseDirectory=' not in wl and 'WOLFRAM_USERBASE' not in wl
    assert wl.count('FindFile["FeynCalc`"]')==2
    assert 'InputForm,PageWidth->Infinity' in wl and str(p/'FeynCalc') in wl
    receipt=sidecar(c,s,p)
    assert se.validate_sidecar(receipt,c,s,p,123)[0]['formula']=='0'
    for formula in ('$Failed', 'Indeterminate', 'Integrate[g,x]'):
        receipt['results'][0]['formula']=formula
        with pytest.raises(ValueError):se.validate_sidecar(receipt,c,s,p,123)


def test_symbolic_context_exact_population_and_failed_text():
    check={'kind':'symbolic-record-census','id_field':'id','expected_ids':['a','b'],'text_fields':['formula']}
    sc._requirements([{'id':'formulas','artifact':'output','pointer':'/results','check':check,'meaning':'Structural formula delivery only'}])
    rows=[{'id':'a','formula':'0','status':'delivered'},{'id':'b','formula':'g','status':'delivered'}]
    assert sc._check(rows,check)[0]
    for invalid in (rows[:1],rows+[rows[0]],[rows[0],rows[0]], [rows[0],dict(rows[1],status='failed')]):
        assert not sc._check(invalid,check)[0]
    for value in (None,False,0,'','  '):
        assert not sc._check([rows[0],dict(rows[1],formula=value)],check)[0]


def test_intake_runtime_free_drift_and_approval_refusal(tmp_path,monkeypatch):
    c,task=configuration(tmp_path,monkeypatch)
    monkeypatch.setattr(se,'_external_module',lambda *a:pytest.fail('intake imported external module'))
    monkeypatch.setattr(se,'_conversion_runtime',lambda *a:pytest.fail('intake imported symbolic engine'))
    paths=se.inputs(task,tmp_path)
    assert Path(c['kernel']['path']) in paths and science.adapter({'mode':'symbolic-evaluation','task':task}) is se
    assert science._new_capability({'mode':'symbolic-evaluation','task':task})
    with pytest.raises(ValueError,match='approved supervised'):se.run(task,tmp_path,tmp_path/'out')
    assert not(tmp_path/'out').exists()
    Path(c['script_tree']['root'],'script0.wl').write_text('changed')
    with pytest.raises(ValueError):se.inputs(task,tmp_path)


def test_actual_schema2_plan_preserves_unapproved_status(tmp_path,monkeypatch):
    c,task=configuration(tmp_path,monkeypatch)
    policy={'schema_version':1,'actors':{'proposer':'synthetic-proposer','executor':'synthetic-executor',
        'physics_critic':'synthetic-critic','skeptical_verifier':'synthetic-skeptic','physics_decider':'synthetic-decider'},
        'max_redos':0,'allowed_changed_paths':[],'allowed_stages':['science'],
        'required_checks':[{'id':'custody','kind':'integrity'}],
        'claim_scopes':{'code_delivery':{'checks':['custody'],'actions':['delivery']}}}
    spec={'schema_version':2,'mode':'symbolic-evaluation','source':'Inert native interface control',
        'assumptions':['No CAS/native execution.'],'max_seconds':45,'approval_mode':'scripted_yes',
        'max_attempts':1,'task':task,'review_policy':{'schema_version':1,'policy':policy,
            'correction_contract':{'task_fields':[],'input_slots':[]}}}
    path=tmp_path/'science.json';save(path,spec);rd=tmp_path/'run'
    science.plan(rd,path);science.verify_plan(rd,approved=False)
    assert not(rd/'inputs/science-approval.json').exists()
    Path(c['provider_tree']['root'],'FeynCalc/FeynCalc.m').write_text('late source change')
    with pytest.raises(ValueError):science.verify_plan(rd,approved=False)


def inert_worker(tmp_path,monkeypatch, *, failing_script=None, native_observer=None):
    base=tmp_path/'inputs';c,task=configuration(base,monkeypatch,scripts=3)
    rd=tmp_path/'run';(rd/'inputs').mkdir(parents=True)
    save(rd/'inputs/science-plan.json',{})
    from ravel.physics import science_worker as worker, reinterpret_db
    spec={'schema_version':2,'mode':'symbolic-evaluation','task':task,'source':'Inert control',
          'assumptions':['No CAS or scientific runtime executed.']}
    selected={'max_seconds':45,'output_directory':'outputs/attempt-1','base_dir':str(base),
              'stage_binding':{'input_snapshot':[]}}
    for module in (science,worker):
        monkeypatch.setattr(module,'verify_worker',lambda *a:selected)
        monkeypatch.setattr(module,'execution_spec',lambda *a:spec)
    monkeypatch.setattr(se,'_conversion_runtime',lambda *a:None)
    parser=SimpleNamespace(_parse_structured_output=lambda text:{'raw':text,'scope':'explicit inert parser'})
    monkeypatch.setattr(se,'_external_module',lambda path,name,digest:parser if 'parser' in name else Converter())
    calls=[]
    def native(command,out,doc):
        if native_observer is not None:native_observer()
        calls.append((command,doc['max_seconds']))
        s=next(s for s in c['scripts'] if s['id']==out.name)
        save(out/'native-process.json',{'pid':123})
        save(out/'native-stdout.log','SYMBOLIC_RESULT['+s['results'][0]['id']+']: old\n continued\nSTATUS: complete\n')
        save(out/'native-stderr.log','')
        if out.name==failing_script:raise ValueError('inert phase failure')
        save(out/'canonical-symbolic.json',sidecar(c,s,rd/'work/symbolic-evaluation/attempt-1/provider'))
        return {'inert':True,'native_calls':0}
    monkeypatch.setattr(reinterpret_db,'execute_native',native)
    code=worker.main([str(rd)])
    return rd, code, calls, c, task


def test_actual_common_worker_serialization_reports_all_results(tmp_path,monkeypatch):
    rd,code,calls,_,_=inert_worker(tmp_path,monkeypatch)
    out=rd/'outputs/attempt-1';result=json.loads((out/'result.json').read_text())
    assert code==0 and len(calls)==3 and calls[0][1]>calls[1][1]>calls[2][1]
    assert result['status']=='passed' and len(result['results'])==3 and result['delivered_results']==3
    assert result['original_task_complete'] is False and result['physics_validated'] is False
    assert 'width2' in (out/'symbolic-report.md').read_text()
    assert 'symbolic-report.md' in (out/'RESULT.md').read_text()
    assert (out/'checkin2.json').exists() and (out/'script0/upstream-parsed.json').exists()


def test_failure_retains_attempted_and_unissued_original_population(tmp_path,monkeypatch):
    rd,code,calls,_,_=inert_worker(tmp_path,monkeypatch,failing_script='script1')
    out=rd/'outputs/attempt-1';result=json.loads((out/'result.json').read_text())
    assert code==3 and len(calls)==2
    assert [r['status'] for r in result['results']]==['delivered','attempted_unresolved','unattempted']
    assert len(result['expected_result_ids'])==3 and (out/'script1/attempt.json').exists()
    assert 'unattempted' in (out/'symbolic-report.md').read_text()


def test_common_publication_rejects_late_raw_artifact_change(tmp_path,monkeypatch):
    original=se.write_report
    def altered(result,out):
        tables=original(result,out)
        (Path(out)/'script0/canonical-symbolic.json').write_text('{}\n')
        return tables
    monkeypatch.setattr(se,'write_report',altered)
    with pytest.raises(ValueError,match='original bytes changed'):
        inert_worker(tmp_path,monkeypatch)


def test_existing_wolfram_locations_survive_all_native_boundaries(tmp_path,monkeypatch):
    locations={'WOLFRAM_USERBASE':'/synthetic/existing-user-location',
               'WOLFRAM_BASE':'/synthetic/existing-system-location'}
    for key,value in locations.items():monkeypatch.setenv(key,value)
    monkeypatch.setenv('WOLFRAMINIT','synthetic unwanted init')
    calls=[]
    def observe():
        calls.append({key:os.environ.get(key) for key in locations})
        assert 'WOLFRAMINIT' not in os.environ
    rd,code,_,_,_=inert_worker(tmp_path,monkeypatch,native_observer=observe)
    assert code==0 and calls==[locations]*3
    assert all(os.environ.get(key)==value for key,value in locations.items())
    assert not set(locations).intersection(se.INIT_ENVIRONMENT)
    assert os.environ['WOLFRAMINIT']=='synthetic unwanted init'


def test_boolean_numerical_return_retains_failed_point():
    d=result_decl()
    result=se.convert_result({'id':'width','symbol':'width','formula':'0'},d,Converter(value=True))
    assert result['status']=='failed' and result['conversion_status']=='delivered'
    assert result['points'][0]['status']=='failed' and result['points'][0]['real'] is None


@pytest.mark.parametrize('raw',['{"x":1,"x":2}','{"x":NaN}','{"x":1e999}'])
def test_exact_canonical_json_rejects_ambiguous_numbers(raw):
    with pytest.raises(ValueError):se._strict_json(raw)


def test_typed_symbolic_artifact_to_report(tmp_path):
    row={'id':'width','formula':'g*Conjugate[g]','status':'delivered','real':5.0,'imag':0.0}
    tool=save(tmp_path/'tool.json',{'rows':[row]});basis=save(tmp_path/'basis.txt','Synthetic complete declared formula and pair.')
    tool['size']=Path(tool['path']).stat().st_size;basis['size']=Path(basis['path']).stat().st_size
    tool['path']='tool.json';basis['path']='basis.txt'
    artifact={'schema_version':1,'basis':[basis],'tools':{'symbolic':tool},'interpretation':{},
        'contract':{'source_scope':'Synthetic symbolic delivery only','tool_fields':[{'field':'rows',
            'type':{'type':'array','max_items':1,'items':{'type':'object','properties':{'id':'string','formula':'string',
                'status':'string','real':'number','imag':'number'}}},
            'source':{'kind':'direct','tool_id':'symbolic','pointer':'/rows'}}],
            'interpretation_fields':[],'unresolved_semantics':[],'max_artifact_bytes':4096}}
    facts=[{'id':field,'selector':{'kind':'record','pointer':'/rows','id_field':'id','row_id':'width','field':field},
        'quantity_id':None,'context_selector':None,'label':field,'unit':'1','scope':'synthetic transport',
        'population':'one requested result','limitations':['No native or scientific qualification.']} for field in ('formula','real','imag')]
    request={'schema_version':1,'title':'Symbolic result','artifact_request':artifact,'context':None,'facts':facts,
        'sections':[{'id':'table','kind':'table','caption':'Complete synthetic row','columns':['Formula','Real','Imaginary'],
            'rows':[{'id':'width','facts':['formula','real','imag']}]}],'interpretation':[]}
    from test_scientific_context import request as context_request, attempt
    context=context_request(tmp_path)
    context['requested_quantities']=[{'id':'formulas','artifact':'records','pointer':'/rows',
        'check':{'kind':'symbolic-record-census','id_field':'id','expected_ids':['width'],'text_fields':['formula']},
        'meaning':'Complete symbolic text only; no formula correctness or numerical equivalence.'}]
    compiled=sc.compile_context(context,tmp_path)
    completed=sc.apply_step(compiled,attempt({'records':{'path':'tool.json','sha256':tool['sha256']}}),tmp_path)
    context_pin=save(tmp_path/'context.json',completed);context_pin['size']=(tmp_path/'context.json').stat().st_size
    context_pin['path']='context.json';request['context']=context_pin
    for fact in facts:
        fact['quantity_id']='formulas'
        fact['context_selector']={**fact['selector'],'pointer':''}
    report=scientific_report.compose(request,base_dir=tmp_path)
    assert 'g*Conjugate[g]' in report['report_text'] and not report['scientific_acceptance']
