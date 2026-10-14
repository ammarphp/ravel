"""Isolated child: original EasyScan CLI and recording-only observer."""
import hashlib
import json
import os
from pathlib import Path
import sys


def loaded_native_assets(request):
    """Bind imported native framework/dependency code to supplied runtime leaves.

    This is source/runtime custody, not loaded-library ABI qualification. Python
    standard-library/platform internals remain the interpreter's runtime premise.
    """
    from ravel.physics import dataset_query_quantities as integrity
    names={'easyscan_hep','scanner','scan_controller','program','readin_config','initialize','auxfun','ploter','constraint','emcee','dynesty','numpy','scipy','matplotlib','pandas'}
    selected={}
    for name,module in tuple(sys.modules.items()):
        if name.split('.')[0] not in names or module is None:continue
        source=getattr(module,'__file__',None)
        if source is None:continue
        path=str(Path(source).absolute())
        if path not in request['assets']:raise ValueError('native imported code outside captured framework/runtime: '+name)
        selected[path]=request['assets'][path]
    integrity.asset_check(selected)
    return {name:str(Path(getattr(module,'__file__')).absolute()) for name,module in tuple(sys.modules.items()) if name.split('.')[0] in names and module is not None and getattr(module,'__file__',None)}


def main(argv=None):
    args=sys.argv[1:] if argv is None else argv
    if len(args)!=2:raise ValueError('exact admitted worker request and digest required')
    path=Path(args[0]);raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args[1]:raise ValueError('native request differs')
    request=json.loads(raw);source=Path(request['source_root'])
    if source.name!='ravel':raise ValueError('actual bound Ravel source package required')
    sys.path.insert(0,str(source.parent))
    from ravel.physics import parameter_space_sampling_core as core
    from ravel.physics import dataset_query_quantities as integrity
    from ravel.physics.parameter_space_sampling_observer import Observer,check_workspace
    request=core.strict(raw)
    if sys.version_info<(3,10):raise ValueError('Ravel child source requires Python>=3.10; original EasyScan requirement>=3.9 remains disclosed')
    integrity.closed_assets(request['assets'],request['closed_roots'])
    c=request['config'];info=request['info'];work=Path(request['work']);out=Path(request['output'])
    obs=None;error=None;emitted=core.Emitted(out)
    try:
        if c['operation']=='read-returned':
            result=request['returned']['observation']
            if type(result) is not dict:raise ValueError('complete original observation required')
            atomic=__import__('ravel.workflow.state_io',fromlist=['atomic_json']).atomic_json
            emitted.json(out/'observation.json',{**result,'fresh_native_execution':False,'supplied_native_return':True},atomic)
        else:
            if info['workers']>1:
                import multiprocessing
                if multiprocessing.get_start_method()!='fork':raise ValueError('released nested parallel worker functions require a supplied fork-compatible runtime; no silent process-method rewrite')
            os.chdir(work);os.environ['EASYSCAN_RESULT_EXISTS_ACTION']='stop';os.environ['EASYSCAN_ROOT']=request['framework'];os.environ['PYTHONDONTWRITEBYTECODE']='1';os.environ['MPLCONFIGDIR']=str(out/'mplconfig')
            sys.argv=['easyscan',request['ini']]+(['--resume'] if c['operation']=='continue-native' else [])
            # Native runtime imports happen only after approved worker custody.
            for site in reversed(request['site_roots']):sys.path.insert(0,site)
            sys.path.insert(0,request['framework']);sys.path.insert(0,str(Path(request['framework'])/'src'))
            import easyscan_hep.cli as cli
            import scanner
            from program import PROGRAM
            obs=Observer(request);obs.install_scanner(scanner);obs.install_program(PROGRAM)
            if info['method']=='EMCEE':
                import emcee
                obs.install_sampler(emcee,'EnsembleSampler','run_mcmc')
            if info['method']=='DYNESTY':
                import dynesty
                obs.install_sampler(dynesty,'NestedSampler','run_nested')
            if info['method']=='BESTFIT':
                import scipy.optimize as optimize
                def factory(fn):
                    def invoke(*aa,**kk):
                        rr=fn(*aa,**kk)
                        from ravel.physics.parameter_space_sampling_observer import value
                        fields=value({k:getattr(rr,k,None) for k in ('x','fun','success','message','nit','nfev')})
                        obs.record('optimizer-return',{'native_fields':fields});obs.optimizer=fields;return rr
                    return invoke
                obs.bind(optimize,'differential_evolution',factory)
            loaded_native_assets(request)
            cli.main()
            obs.record('native-module-origins',{'modules':loaded_native_assets(request)})
            if obs.counters['failed'].value:raise ValueError('observer recorded a failure')
            obs.final('completed')
    except BaseException as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        if obs is not None:obs.final('failed',error)
        else:
            from ravel.workflow.state_io import atomic_json
            emitted.json(out/'observation.json',{'schema_version':1,'status':'failed','exception':error,'counts':{},'workers':[],'samplers':{},'fresh_native_execution':False},atomic_json,replace=(out/'observation.json') in emitted.expected)
    finally:
        if obs is not None:obs.restore()
    # Ending checks execute even after a native error, without rewriting raw
    # programme outputs. All upstream Recover edits are confined to this copy.
    check_workspace(request);integrity.closed_assets(request['assets'],request['closed_roots'])
    if obs is not None:obs._finish_emitted()
    emitted.finish()
    if path.read_bytes()!=raw:raise ValueError('ending admitted worker request differs')
    return 1 if error else 0


if __name__=='__main__':raise SystemExit(main())
