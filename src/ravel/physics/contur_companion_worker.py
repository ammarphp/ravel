"""Private source-bound Contur companion observer; no native algorithm copies."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, redirect_stdout
from copy import deepcopy
import hashlib
import importlib
import io
import math
import os
from pathlib import Path
import sys
import uuid

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'

from ravel.physics import contur_companion as api
from ravel.workflow import execution, science
from ravel.workflow.state_io import read_json

# These finite line observations refer only to the separately distributed,
# hash-admitted released module. They do not copy its implementation.
SM_SOURCE_SHA = '25121cccf6710d713312e79294871b271804c4606831c4c37777257f39ccac74'
SM_SKIPS = {167:'analysis_not_selected',171:'no_sm_predictions',190:'theory_file_read_once',
            207:'invalid_histogram',215:'no_pool',228:'no_theory_plot'}
_ORIGINAL_EXECUTE = None


def detached(value):
    """Retain native None/nonfinite explicitly; never serialize it as zero."""
    if value is None or type(value) in (str, bool, int): return value
    if type(value) is float:
        return value if math.isfinite(value) else {'native_nonfinite':repr(value)}
    if isinstance(value, dict):
        if any(not isinstance(k,str) for k in value):
            return {'native_mapping_entries':[[detached(k),detached(v)] for k,v in value.items()]}
        return {k:detached(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)): return [detached(v) for v in value]
    if hasattr(value,'item'):
        return detached(value.item())
    raise ValueError('unsupported native value type: '+type(value).__name__)


@contextmanager
def wrappers(items):
    originals=[]
    try:
        for obj,name,build in items:
            original=getattr(obj,name); originals.append((obj,name,original))
            setattr(obj,name,build(original))
        yield
    finally:
        for obj,name,original in reversed(originals): setattr(obj,name,original)


def _native_function(function, source_root, files):
    code=getattr(function,'__code__',None)
    if code is None: raise ValueError('native observer requires released Python function')
    path=Path(code.co_filename).absolute()
    if not path.is_relative_to(source_root): raise ValueError('native function outside bound source')
    rel=path.relative_to(source_root).as_posix()
    if rel not in files or api.custody._sha(path)!=files[rel]:
        raise ValueError('native function source changed')


def delegated_parent(rundir, doc, work):
    rd=science.root(rundir); proposal=read_json(rd/science.PLAN); spec=science.execution_spec(rd)
    stage=execution.load_execution(rd)['stages'].get('science',{}); approval=read_json(rd/science.APPROVAL)
    if (spec['schema_version']!=2 or spec['mode']!='contur-companion' or spec['max_attempts']!=1
            or stage.get('status')!='running' or stage.get('child_pid')!=os.getppid()
            or stage.get('child_identity')!=execution.process_identity(os.getppid())
            or stage.get('fingerprint')!=proposal['stage_binding']['fingerprint']
            or approval.get('plan_sha256')!=api.custody._sha(rd/science.PLAN)
            or Path(work)!=rd/proposal['stages'][0]['outputs'][0]/'contur-companion-work'):
        raise ValueError('companion requires live exact ordinary parent delegation')
    path, original=api._load(spec['task'],proposal['base_dir'])
    if doc!=api.resolved_document(original,path.parent):
        raise ValueError('native prepared companion differs from approved original')


class _LimitedText(io.StringIO):
    def __init__(self):
        super().__init__();self.byte_count=0
    def write(self,text):
        size=len(text.encode('utf-8'))
        if self.byte_count+size>1024*1024:
            raise ValueError('native renderer diagnostic exceeds one MiB')
        returned=super().write(text);self.byte_count+=size;return returned


def render_script(script, plot_dir='', multiprocess=False, shared_modules_list=None, print_script=True):
    """Forward the original native renderer; also callable in its spawned worker.

    The original dispatcher still creates the descendants. The declared binding
    only routes finite observer receipts; it does not authorize a scientific call.
    """
    binding_path=os.environ.get('RAVEL_CONTUR_RENDER_BINDING')
    binding_sha=os.environ.get('RAVEL_CONTUR_RENDER_BINDING_SHA256')
    if not binding_path or api.custody._sha(science.regular(binding_path,Path.cwd()))!=binding_sha:
        raise ValueError('renderer has no bound ordinary companion observation')
    binding=read_json(binding_path); work=Path(binding['work'])
    if Path(binding_path)!=work/'render-binding.json': raise ValueError('foreign renderer binding location')
    input_path=work/'native-input.json'
    if api.custody._sha(input_path)!=binding['input_sha256']:
        raise ValueError('renderer prepared source changed')
    _,doc,runtime,bundles,files=api.admission({'input':str(input_path)},work)
    original_inputs={str(p):api.custody._sha(p) for p in files}
    path=science.regular(script,work)
    if not path.is_relative_to(work): raise ValueError('foreign native rendering script')
    before=api.custody._sha(path)
    output_root=Path(plot_dir).absolute() if plot_dir else path.parent
    if not output_root.is_relative_to(work): raise ValueError('renderer output outside owned workspace')
    native=importlib.import_module('contur.util.utils')
    original=_ORIGINAL_EXECUTE or native.executeScript
    if original is render_script: raise ValueError('recursive native renderer substitution')
    _native_function(original,bundles['source']['root'],bundles['source']['manifest']['files'])
    figure=importlib.import_module('matplotlib.figure').Figure
    saves=[]; diagnostic=_LimitedText(); original_stdout=sys.stdout
    def saved(original_save):
        def call(self, filename, *args, **kwargs):
            if not isinstance(filename,(str,os.PathLike)):
                raise ValueError('opaque native figure destination is not admitted')
            target=Path(filename).absolute()
            if not target.is_relative_to(work): raise ValueError('native figure outside owned workspace')
            row={'path':str(target),'status':'attempted'}; saves.append(row)
            try:
                result=original_save(self,filename,*args,**kwargs)
                science.regular(target,work)
                if not target.stat().st_size: raise ValueError('native rendered product is empty')
                row.update(status='written',sha256=api.custody._sha(target),size=target.stat().st_size)
                return result
            except BaseException as exc:
                row.update(status='failed',error=type(exc).__name__+': '+str(exc)); raise
        return call
    row={'script':str(path),'script_sha256':before,'plot_dir':str(output_root),
         'native_multiprocess':multiprocess,'status':'failed','saves':saves}
    import multiprocessing
    row['observed_start_method']=multiprocessing.get_start_method(allow_none=True)
    row['observer_route']='native Pool body savefig callback' if multiprocess else 'original serial shell call + finite source target census'
    try:
        # Pool workers execute their original Python body directly. The native
        # serial branch starts another Python via a shell; that grandchild cannot
        # inherit this callback, so its output targets are read from its original
        # generated script declarations instead of claiming callback coverage.
        with wrappers([(figure,'savefig',saved)]),redirect_stdout(diagnostic):
            returned=original(script,plot_dir,multiprocess,shared_modules_list or [],print_script)
        row['native_return']=detached(returned)
        row['native_diagnostic']=diagnostic.getvalue()
        if not multiprocess:
            row['saves']=serial_products(path,output_root,work)
        if (not row['saves'] or any(r['status']!='written' for r in row['saves'])
                or 'Unexpected error when executing' in row['native_diagnostic']):
            raise ValueError('native renderer failed or required output population is absent')
        if api.custody._sha(path)!=before: raise ValueError('native render script changed')
        source_root=bundles['source']['root']
        source={str(source_root/r):sha for r,sha in bundles['source']['manifest']['files'].items()}
        dependencies={str(api.custody._pin(pin,Path(doc['runtime']['manifest']['path']).parent)):pin['sha256'] for pin in runtime['files']}
        dependencies[str(Path(__file__).absolute())]=api.custody._sha(Path(__file__).absolute())
        row['loaded_modules']=api.custody.module_witness(source_root,source,dependencies)
        if original_inputs!={str(p):api.custody._sha(p) for p in api.inputs({'input':str(input_path)},work)}:
            raise ValueError('renderer source/runtime/input changed')
        row['status']='returned'
        return returned
    except BaseException as exc:
        row['error']=type(exc).__name__+': '+str(exc); raise
    finally:
        original_stdout.write(diagnostic.getvalue())
        api.write_new(work/'render-receipts'/('render-'+uuid.uuid4().hex+'.json'),row)


def serial_products(script, output_root, work):
    """Resolve only finite native path declarations; never execute an AST.

    The released profile generator uses __file__/plotDir/os.path.join and
    string suffixes. Its serial branch has no YODA_USER_PLOT_PATH global.
    Other expressions or control flow affecting savefig refuse explicitly.
    """
    import ast
    script=Path(script); tree=ast.parse(script.read_text()); paths=[]
    environment={'__file__':str(script.absolute())}
    def value(node):
        if isinstance(node,ast.Constant) and type(node.value) in (str,int):return node.value
        if isinstance(node,ast.Name) and node.id in environment:return environment[node.id]
        if isinstance(node,ast.BinOp) and isinstance(node.op,ast.Add):
            left,right=value(node.left),value(node.right)
            if isinstance(left,str) and isinstance(right,str):return left+right
        if isinstance(node,ast.Call) and not node.keywords:
            name=ast.unparse(node.func);args=[value(x) for x in node.args]
            if name=='os.path.realpath' and len(args)==1 and args[0]==str(script.absolute()):return args[0]
            if name=='os.path.split' and len(args)==1 and isinstance(args[0],str):return os.path.split(args[0])
            if name=='os.path.join' and args and all(isinstance(x,str) for x in args):return os.path.join(*args)
        if isinstance(node,ast.Subscript) and isinstance(node.slice,ast.Constant):
            seq=value(node.value);index=node.slice.value
            if isinstance(seq,tuple) and type(index) is int and index in (0,1):return seq[index]
        raise ValueError('serial generated renderer requires literal or released finite source path declarations')
    def walk(statements):
        for statement in statements:
            if isinstance(statement,ast.Assign):
                for target in statement.targets:
                    if isinstance(target,ast.Name):
                        environment.pop(target.id,None)
                        try:environment[target.id]=value(statement.value)
                        except ValueError:pass
            elif isinstance(statement,ast.If):
                # Exact released serial profile branch; no dynamic evaluation.
                if ast.unparse(statement.test)=="'YODA_USER_PLOT_PATH' in globals()":walk(statement.orelse)
                elif any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='savefig' for n in ast.walk(statement)):
                    raise ValueError('unsupported serial output control flow')
            elif isinstance(statement,ast.Expr) and isinstance(statement.value,ast.Call):
                call=statement.value
                if isinstance(call.func,ast.Attribute) and call.func.attr=='savefig':
                    if not call.args:raise ValueError('serial figure destination absent')
                    raw=value(call.args[0])
                    if not isinstance(raw,str):raise ValueError('serial figure destination is not a string')
                    target=Path(raw);target=target if target.is_absolute() else Path(output_root)/target
                    if not target.absolute().is_relative_to(work):raise ValueError('foreign serial figure target')
                    science.regular(target,work)
                    if not target.stat().st_size:raise ValueError('empty native serial figure')
                    paths.append({'path':str(target.absolute()),'status':'written','sha256':api.custody._sha(target),'size':target.stat().st_size})
            elif not isinstance(statement,(ast.FunctionDef,ast.ClassDef)) and any(
                    isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='savefig' for n in ast.walk(statement)):
                raise ValueError('unsupported serial output control flow')
    walk(tree.body)
    if not paths:raise ValueError('no verifiable serial renderer targets')
    return paths


def _identity(local):
    analysis=local.get('analysis'); prediction=local.get('prediction'); thy=local.get('thy')
    return {'analysis':getattr(analysis,'name',local.get('ana')),
            'pool':getattr(analysis,'poolid',None), 'prediction':getattr(prediction,'id',None),
            'theory_file':getattr(prediction,'file_name',None),
            'histogram':thy.path() if thy is not None else None}


def _sm_trace(module, observed):
    def trace(frame,event,arg):
        if frame.f_code is module.main.__code__:
            local=frame.f_locals
            if event=='line' and frame.f_lineno in SM_SKIPS:
                observed['skipped'].append({**_identity(local),'reason':SM_SKIPS[frame.f_lineno]})
            if event=='line' and frame.f_lineno==165:
                a=local['analysis']; predictions=getattr(a,'sm_predictions',None)
                observed['analyses'].append({'name':a.name,'pool':a.poolid,
                    'predictions':None if predictions is None else
                    [{'id':p.id,'file':p.file_name} for p in predictions]})
            if event=='line' and frame.f_lineno==201:
                observed['theory_populations'].append({**_identity(local),
                    'paths':[obj.path() for obj in local['aos'].values()]})
            if event=='line' and frame.f_lineno==252:
                value=local['pv']; observed['pvalues'].append({**_identity(local),'native_name':local['name'],
                    'backend':'spey' if observed['use_spey'] else 'default', 'value':detached(value),
                    'status':'none' if value is None else 'nonfinite' if not math.isfinite(float(value)) else 'finite',
                    'unit':'dimensionless'})
            if event=='exception':
                observed['exceptions'].append({'type':arg[0].__name__,'message':str(arg[1]),'line':frame.f_lineno})
            if event=='return':
                observed['native_dictionary']=detached(local.get('pvalues',{}))
                observed['native_probability_populations']=detached(local.get('probs',{}))
        return trace
    return trace


def execute_operation(doc, bundles, work, modules):
    """Call the released entry using detached observations, not a substitute law."""
    operation=doc['operation']; cfg=modules['config']; util=modules['utils']; module=modules['operation']
    source=bundles['source']; _native_function(module.main if operation!='herwig-xs-br' else module.run_extract_xs_bf,
                                               source['root'],source['manifest']['files'])
    observed={'operation':operation,'requested_options':deepcopy(doc['options']),
              'source_version':api.VERSION,'source_commit':api.COMMIT,'renderer_calls':[],'phase':'running'}
    renderer_items=[]
    def render_dispatch(original):
        def call(scripts,numcores=1):
            scripts=list(scripts)
            for script,directory in scripts:
                p=science.regular(script,work)
                if not p.is_relative_to(work): raise ValueError('render script outside fresh native work')
                observed['renderer_calls'].append({'script':str(p),'sha256':api.custody._sha(p),
                                                   'directory':str(directory),'native_cores':numcores})
            if not 1<=numcores<=doc['renderer_cores']:
                raise ValueError('actual native renderer cores exceed prospective admission')
            return original(scripts,numcores)
        return call
    def cores(original):
        def call(requested):
            native=original(requested)
            observed.setdefault('renderer_core_observations',[]).append({'requested':requested,'native_available':native,
                'admitted':doc['renderer_cores'],'policy':'native return unchanged; actual dispatch must fit admitted ceiling'})
            return native
        return call
    renderer_items=[(util,'make_mpl_plots',render_dispatch),(util,'get_numcores',cores)]
    global _ORIGINAL_EXECUTE
    _ORIGINAL_EXECUTE=util.executeScript
    renderer_items.append((util,'executeScript',lambda original:render_script))
    args=modules['arg_utils'].get_args(api.arguments(doc,bundles,work),api.ENTRIES[operation][1])
    observed['parsed_arguments']=detached(args)
    patches=renderer_items; old_trace=sys.gettrace()
    if old_trace is not None: raise ValueError('native companion requires an untraced fresh interpreter')
    if operation=='sm-test':
        if api.custody._sha(Path(module.main.__code__.co_filename))!=SM_SOURCE_SHA:
            raise ValueError('SM branch observer requires exact released loop source')
        observed.update(analyses=[],skipped=[],theory_populations=[],pvalues=[],exceptions=[],use_spey=doc['options']['use_spey'])
    elif operation=='herwig-xs-br':
        helpers=modules['herwig']
        def capture(name):
            def build(original):
                def call(*args,**kwargs):
                    value=original(*args,**kwargs)
                    observed[name]=detached(value)
                    return value
                return call
            return build
        patches += [(helpers,name,capture(name)) for name in
                    ('get_particle_properties','build_herwig_ME_map','get_herwig_cross_sections')]
        observed['source_unit_profile']=api.herwig_profile(work/'input'/bundles['payload']['root'].name,doc)
    elif operation=='map-plots':
        def read_db(original):
            def call(*args,**kwargs):
                depot=original(*args,**kwargs)
                observed['points']=[{'parameters':detached(p.parameter_values),
                    'full_likelihood_results':detached(p.full_likelihood_results),
                    'pool_results':detached(p.sorted_blocks_results)} for p in depot.points]
                return depot
            return call
        def plot_base(original):
            def call(*args,**kwargs):
                obj=original(*args,**kwargs); remaining=set(obj.get_parameters(variables_only=True))-set(doc['options']['variables'])
                if any(name not in obj.map_axis for name in doc['options']['variables']):
                    raise ValueError('requested native plot variables are absent')
                if set(doc['options']['slice'])!=remaining:
                    raise ValueError('complete explicit native variable-parameter slice required')
                if any(name not in obj.map_axis or value not in obj.map_axis[name]
                       for name,value in doc['options']['slice'].items()):
                    raise ValueError('declared slice is not an existing native coordinate')
                observed['native_variable_parameters']=list(obj.get_parameters(variables_only=True))
                native_metric=obj.is_plot_metric_valid
                def metric(*a,**kw):
                    returned=native_metric(*a,**kw)
                    observed.setdefault('metric_availability',[]).append({'metric':a[0],'available':returned})
                    return returned
                obj.is_plot_metric_valid=metric
                native_plot=obj.plot_figures
                def plotted(*a,**kw):
                    start=len(observed.get('figure_calls',[]));errors=[];old=sys.gettrace()
                    def trace(frame,event,arg):
                        if event=='exception' and Path(frame.f_code.co_filename).name=='contur_plot.py':
                            errors.append({'type':arg[0].__name__,'message':str(arg[1]),'line':frame.f_lineno})
                        return trace
                    try:
                        sys.settrace(trace);returned=native_plot(*a,**kw)
                    finally:sys.settrace(old)
                    calls=observed.get('figure_calls',[])[start:]
                    observed.setdefault('metric_plots',[]).append({'metric':a[0],'levels':detached(a[1]),
                        'scale':a[2],'save_calls':len(calls),'caught_native_exceptions':errors})
                    if errors or not calls:raise ValueError('native selected metric did not complete its figure population')
                    return returned
                obj.plot_figures=plotted
                return obj
            return call
        patches += [(module,'read_run_db',read_db),(module,'create_plotbase',plot_base)]
        figure=modules['figure'].Figure
        def save(original):
            def call(self,path,*args,**kwargs):
                target=Path(path).absolute()
                if not target.is_relative_to(work): raise ValueError('native map output outside work')
                row={'path':str(target),'status':'attempted'}; observed.setdefault('figure_calls',[]).append(row)
                try:
                    returned=original(self,path,*args,**kwargs); science.regular(target,work)
                    if not target.stat().st_size: raise ValueError('empty native map figure')
                    row.update(status='written',sha256=api.custody._sha(target),size=target.stat().st_size); return returned
                except BaseException as exc:
                    row.update(status='failed',error=str(exc)); raise
            return call
        patches.append((figure,'savefig',save))
    else:
        def capture(name):
            def build(original):
                def call(*args,**kwargs):
                    value=original(*args,**kwargs)
                    if name=='resolve_beam_and_runpoint': observed[name]=detached(value)
                    elif name=='build_histograms':
                        observed[name]=[{'pool':pool.id,'analyses':[{'name':a.name,'histograms':detached(rows)}
                            for a,rows in analyses.items()]} for pool,analyses in value.items()]
                    elif name=='build_pool_exclusions':
                        observed[name]=[{'pool':pool.id,'results':detached(rows)} for pool,rows in value.items()]
                    elif name=='selected_histograms':
                        observed[name]=[{'pool':r.pool.id,'analysis':r.analysis.name,'histogram':r.histogram,
                            'exclusions':detached(r.excl),'matched_cls':r.matched_cls,'scripts':detached(r.scripts)} for r in value]
                    return value
                return call
            return build
        patches += [(module,name,capture(name)) for name in ('resolve_beam_and_runpoint','build_histograms','build_pool_exclusions','selected_histograms')]
    try:
        with wrappers(patches):
            if operation=='sm-test': sys.settrace(_sm_trace(module,observed))
            returned=(module.run_extract_xs_bf(args) if operation=='herwig-xs-br' else module.main(args))
            observed['native_return']=detached(returned)
        observed['phase']='returned'
    except BaseException as exc:
        observed['phase']='failed'; observed['error']=type(exc).__name__+': '+str(exc); raise
    finally:
        sys.settrace(old_trace); _ORIGINAL_EXECUTE=None
        observed['effective_configuration']={k:detached(getattr(cfg,k,None)) for k in
            ('stat_types','primary_stat','offline','multi_p','use_spey','config_file','output_dir',
             'exclude_searches','exclude_met_ratio','exclude_hgg','exclude_hww','exclude_b_veto','exclude_awz','exclude_soft_physics','tracks_only')}
        observed['outputs']=api.bounded_inventory(work/'native-output') if (work/'native-output').is_dir() else {}
        observed['render_receipts']=[read_json(p) for p in sorted((work/'render-receipts').glob('*.json'))]
        fields=sorted(observed)
        pin=api.write_new(work/'operation-observation.json',observed)
        observed['operation_record_commitment']={'pin':pin,'fields':fields}
        verify_operation_record(observed,work)
    return observed


def verify_operation_record(observed,work):
    """Carry intended phase bytes and their detached values through delivery."""
    path=Path(work)/'operation-observation.json'
    commitment=observed.get('operation_record_commitment')
    if commitment is None:
        # Inert caller controls can provide observations without an executed
        # phase. A genuine phase record can never omit its original commitment.
        if path.exists():raise ValueError('native operation record commitment absent')
        return
    api._keys(commitment,('pin','fields'),'operation record commitment')
    pin=commitment['pin'];fields=commitment['fields']
    if (Path(pin['path'])!=path or not isinstance(fields,list) or not fields
            or fields!=sorted(set(fields)) or any(k not in observed for k in fields)
            or 'operation_record_commitment' in fields):
        raise ValueError('native operation record identity/field population differs')
    api.verify_emitted_value(pin,{key:observed[key] for key in fields})
    if read_json(path)!={key:observed[key] for key in fields}:
        raise ValueError('native operation record detached values differ')


def reconcile(doc, observed, work):
    if observed.get('phase')!='returned' or observed.get('operation')!=doc['operation']:
        raise ValueError('native companion did not complete its declared operation')
    work=Path(work); operation=doc['operation']
    for call in observed.get('figure_calls',[]):
        if call.get('status')!='written': raise ValueError('a native map figure failed')
        api.verify_emitted([call])
    calls=observed.get('renderer_calls',[]); receipts=observed.get('render_receipts',[])
    expected=[(r['script'],r['sha256']) for r in calls]
    actual=[(r['script'],r['script_sha256']) for r in receipts]
    if sorted(expected)!=sorted(actual): raise ValueError('complete native renderer call/receipt census differs')
    for receipt in receipts:
        if receipt.get('status')!='returned' or not receipt.get('saves'):
            raise ValueError('native renderer receipt failed')
        for save in receipt['saves']: api.verify_emitted([save])
    if operation=='sm-test':
        if not observed.get('analyses') or not observed.get('pvalues'):
            raise ValueError('empty native SM getter population cannot be successful')
        cfg=observed['effective_configuration']
        if cfg['stat_types']!=['SMBG'] or any(cfg[k] is not False for k in
                ('exclude_searches','exclude_met_ratio','exclude_hgg','exclude_hww','exclude_b_veto','exclude_awz','exclude_soft_physics','tracks_only')):
            raise ValueError('native SM reset/covariance profile differs')
        if cfg['use_spey']!=doc['options']['use_spey']: raise ValueError('native SM backend differs')
        if not any(name.startswith('probs_') and name.endswith('.pdf') for name in observed['outputs']):
            raise ValueError('native SM probability figures absent')
    elif operation=='herwig-xs-br':
        if not all(name in observed for name in ('get_particle_properties','build_herwig_ME_map','get_herwig_cross_sections')):
            raise ValueError('incomplete original Herwig helper return population')
        total,processes=observed['get_herwig_cross_sections']
        if not isinstance(processes,dict) or type(total) not in (int,float) or not math.isfinite(total) or total<0:
            raise ValueError('native Herwig total absent/sentinel or invalid')
    elif operation=='map-plots':
        if not observed.get('points') or not observed.get('figure_calls'):
            raise ValueError('native map points or requested figures absent')
        if doc['options']['save_plots'] and 'contur.plot' not in observed['outputs']:
            raise ValueError('requested opaque native plot artifact absent')
    else:
        if not all(k in observed for k in ('resolve_beam_and_runpoint','build_histograms','build_pool_exclusions','selected_histograms')):
            raise ValueError('complete native DB/script/histogram population absent')
        if not observed['selected_histograms']:
            raise ValueError('requested native histogram selection has no products')
        if not any(name.endswith('.html') for name in observed['outputs']):
            raise ValueError('native HTML delivery absent')
    if api.bounded_inventory(work/'native-output')!=observed['outputs']:
        raise ValueError('native output membership or bytes changed')
    verify_operation_record(observed,work)
    return observed


def native_worker(input_path, work, rundir):
    if sys.flags.optimize: raise ValueError('optimized observer runtime is not admitted')
    work=Path(work).absolute(); path=Path(input_path).absolute()
    if path!=work/'native-input.json': raise ValueError('foreign native companion preparation')
    _,doc,runtime,bundles,files=api.admission({'input':str(path)},work)
    delegated_parent(rundir,doc,work)
    originals={str(p):api.custody._sha(p) for p in files}
    mode_baseline,preparation_pin=api.prepared_modes(work)
    before=api.staged_inputs(doc,bundles,work,initial_user=True,mode_baseline=mode_baseline)
    for key,value in runtime['environment'].items():
        if os.environ.get(key)!=value: raise ValueError('native startup environment changed: '+key)
    os.environ['CONTUR_USER_DIR']=str(work/'user'); os.environ['CONTUR_DATA_PATH']=str(bundles['data']['root'])
    sys.path.insert(0,str(bundles['source']['root']/'src'))
    (work/'render-receipts').mkdir(exist_ok=False)
    binding=api.write_new(work/'render-binding.json',{'work':str(work),'input_sha256':api.custody._sha(path)})
    os.environ['RAVEL_CONTUR_RENDER_BINDING']=binding['path']; os.environ['RAVEL_CONTUR_RENDER_BINDING_SHA256']=binding['sha256']
    imported=importlib.import_module('contur')
    if imported.__version__!=api.VERSION: raise ValueError('loaded Contur release differs')
    names={'sm-test':'run_smtest','herwig-xs-br':'run_extract_xs_bf','map-plots':'run_plot','rivet-plots':'run_mkplots'}
    modules={key:importlib.import_module(name) for key,name in {
        'operation':'contur.run.'+names[doc['operation']], 'config':'contur.config.config',
        'utils':'contur.util.utils','arg_utils':'contur.run.arg_utils'}.items()}
    if doc['operation']=='herwig-xs-br': modules['herwig']=importlib.import_module('contur.util.herwig_utils')
    if doc['operation']=='map-plots': modules['figure']=importlib.import_module('matplotlib.figure')
    source_root=bundles['source']['root']; source={str(source_root/r):sha for r,sha in bundles['source']['manifest']['files'].items()}
    dependencies={str(api.custody._pin(pin,Path(doc['runtime']['manifest']['path']).parent)):pin['sha256'] for pin in runtime['files']}
    # A genuine multiprocessing alias has this exact bound worker origin; it is
    # not exempted by module name.
    dependencies[str(Path(__file__).absolute())]=api.custody._sha(Path(__file__).absolute())
    loaded_before=api.custody.module_witness(source_root,source,dependencies)
    api.staged_inputs(doc,bundles,work,initial_user=True,mode_baseline=mode_baseline)
    api.verify_emitted([preparation_pin])
    previous=os.getcwd(); os.chdir(work)
    try: observed=execute_operation(doc,bundles,work,modules)
    finally: os.chdir(previous)
    observed['loaded_before']=loaded_before
    observed['loaded_after']=api.custody.module_witness(source_root,source,dependencies)
    observed['staged_before']=before
    reconcile(doc,observed,work)
    observed['staged_after']=api.staged_inputs(doc,bundles,work,
        generated_products=api.generated_input_products(observed,bundles,work),mode_baseline=mode_baseline)
    emitted=api.write_new(work/'native-observation.json',observed)
    if originals!={str(p):api.custody._sha(p) for p in api.inputs({'input':str(path)},work)}:
        raise ValueError('original native companion dependencies changed')
    api.verify_emitted([binding,emitted,preparation_pin]);reconcile(doc,observed,work)
    api.staged_inputs(doc,bundles,work,generated_products=api.generated_input_products(observed,bundles,work),mode_baseline=mode_baseline)
    api.verify_emitted_value(emitted,observed)
    return observed


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True);parser.add_argument('--work',required=True);parser.add_argument('--rundir',required=True)
    a=parser.parse_args(argv); native_worker(a.input,a.work,a.rundir)


if __name__=='__main__': main()
