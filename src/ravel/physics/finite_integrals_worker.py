"""PySecDec worker; invoked only by the admitted ordinary adapter."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import sysconfig
import time


def _authenticated_driver(request):
    """Observe the exact copied entry source, never exempt a module name."""
    from ravel.physics.source_tables import bounded_read
    declared=request.get('driver')
    if (type(declared) is not dict or set(declared)!= {'path','sha256'} or
        type(declared['path']) is not str or not Path(declared['path']).is_absolute() or
        type(declared['sha256']) is not str or len(declared['sha256'])!=64 or
        any(c not in '0123456789abcdef' for c in declared['sha256'])):
        raise ValueError('exact selected integral driver pin required')
    path=Path(declared['path'])
    if str(path)!=declared['path'] or path!=Path(__file__).absolute():raise ValueError('selected driver differs from actual entry file')
    raw=bounded_read(path,2*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=declared['sha256']:raise ValueError('selected driver bytes changed')
    source=Path(request['ravel_source_root'])/'ravel/physics/finite_integrals_worker.py'
    original=bounded_read(source,2*1024*1024)
    if original!=raw:raise ValueError('selected driver differs from exact worker source')
    if request['runtime_assets'].get(str(path))!=declared['sha256']:raise ValueError('selected driver missing from process input census')
    return {'path':str(path),'sha256':declared['sha256'],'bytes':len(raw),'source_path':str(source)}


def _import_census(request,baseline_modules,stdlib,observed_system,modules=None):
    """All observed source bytes, including the validated multiprocessing alias."""
    driver=_authenticated_driver(request)
    modules=sys.modules if modules is None else modules
    rows=[];seen={};selected=request['runtime_assets']
    for name,module in sorted(modules.items()):
        raw=getattr(module,'__file__',None)
        if name=='__mp_main__':
            if (module is not modules.get('__main__') or raw is None or
                Path(raw).absolute()!=Path(driver['path'])):
                raise ValueError('multiprocessing alias is not the exact main driver module')
        if raw is None:continue
        p=Path(raw).resolve()
        scientific=name.split('.')[0] in {'pySecDec','pySecDecContrib','numpy','sympy','mpmath','yaml'}
        if scientific or name not in baseline_modules or name=='__mp_main__' or any(p.is_relative_to(Path(s)) for s in request['sites']):
            if not scientific and name!='__mp_main__' and p.is_relative_to(stdlib) and not {'site-packages','dist-packages'} & set(p.parts):
                observed_system.add(str(p));continue
            data=p.read_bytes();row={'path':str(p),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
            if selected.get(row['path'])!=row['sha256']:raise ValueError('dependency imported outside exact runtime census: '+name)
            if row['path'] in seen:seen[row['path']]['modules'].append(name)
            else:
                item={'modules':[name],**row};rows.append(item);seen[row['path']]=item
    if not any('pySecDec' in r['modules'] for r in rows):raise ValueError('missing actual pySecDec import')
    return rows


def main(request_path):
    if sys.flags.optimize:raise ValueError('optimized Python is unsupported')
    request=json.loads(Path(request_path).read_text());sys.path[:0]=[request['ravel_source_root'],*request['sites']]
    from ravel.physics import finite_integrals_core as core
    c=core.config(request['config']);out=Path(request['output']);start=time.monotonic()
    os.environ.update(PYTHONDONTWRITEBYTECODE='1',SECDEC_CONTRIB=request['contrib_root'],PATH=request['path'],
                      OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
    scratch=out/'scratch';scratch.mkdir(exist_ok=False);os.environ['TMPDIR']=str(scratch)
    cleared=[]
    for key in ('MAKEFLAGS','MFLAGS','GNUMAKEFLAGS','MAKEFILES','CXXFLAGS','CPPFLAGS','LDFLAGS','SECDEC_WITH_CUDA','SECDEC_WITH_CUDA_FLAGS','NVCCFLAGS','FORMTHREADS','DEBUG','PYTHON'):
        if key in os.environ:cleared.append(key);os.environ.pop(key)
    # A package install is a prerequisite, never performed by this worker.
    baseline_modules=set(sys.modules)
    stdlib=Path(sysconfig.get_path('stdlib')).resolve()
    observed_system=set()
    def filepin(p):
        p=Path(p).resolve();raw=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    def imports():
        return _import_census(request,baseline_modules,stdlib,observed_system)
    def remaining():
        left=c['max_seconds']-(time.monotonic()-start)
        if left<=0:raise TimeoutError('complete provider budget exhausted')
        return left
    spec=core.generator_spec(c)
    state={'status':'running','version':core.VERSION,'generator_spec':spec,'calls_started':0,'calls_returned':0,
           'rows':[],'phases':[],'operation_resources':c['operation_resources'],'cleared_build_environment_keys':cleared,'error':None}
    def save():core.write(out/'native-integrals.json',state)
    save()
    try:
        state['selected_driver']=_authenticated_driver(request);save()
        options=core.compiler_options(c)
        if options:
            compiler=c['build_compatibility']['compiler']
            if request['cxx']!=compiler['path'] or request['runtime_assets'].get(request['cxx'])!=compiler['sha256']:
                raise ValueError('compatibility compiler differs from selected process input census')
            state['build_compatibility']=c['build_compatibility'];save()
        import pySecDec as psd
        from pySecDec.integral_interface import IntegralLibrary
        import pySecDecContrib
        if Path(pySecDecContrib.dirname).resolve()!=Path(request['contrib_root']).resolve():raise ValueError('actual pySecDecContrib differs from admitted tools/data root')
        state['observed_contrib_root']=str(Path(pySecDecContrib.dirname).resolve())
        if psd.__version__!=core.VERSION:raise ValueError('pySecDec release differs')
        state['imports_before']=imports();save();remaining()
        state['phases'].append({'name':'generate','status':'started'});save()
        li=psd.LoopIntegralFromPropagators(propagators=spec['propagators'],loop_momenta=spec['loop_momenta'],
            external_momenta=spec['external_momenta'],replacement_rules=spec['replacement_rules'],
            dimensionality=spec['dimensionality'],powerlist=spec['powerlist'])
        kwargs={k:spec[k] for k in ('name','real_parameters','complex_parameters','requested_orders','contour_deformation',
            'additional_prefactor','enforce_complex','decomposition_method','form_threads','processes','pylink_qmc_transforms')}
        psd.loop_package(loop_integral=li,**kwargs)
        state['phases'][-1]['status']='returned';save();remaining()
        command=[request['make'],'-j1','-C',str(out/'finite_integral'),'pylink','CXX='+request['cxx'],'SECDEC_CONTRIB='+request['contrib_root'],'PYTHON='+sys.executable,'FORMTHREADS=1']
        if options:command.append('CXXFLAGS='+' '.join(options))
        state['phases'].append({'name':'build','status':'started','command':command});save()
        with (out/'build.stdout').open('x') as stdout,(out/'build.stderr').open('x') as stderr:
            completed=subprocess.run(command,stdout=stdout,stderr=stderr,check=False,timeout=remaining())
        state['phases'][-1].update(status='returned',returncode=completed.returncode);save()
        if completed.returncode:raise ValueError('native integral build failed')
        library=out/'finite_integral/finite_integral_pylink.so';state['generated_library']=filepin(library);save()
        api=IntegralLibrary(str(library));state['library_info']={str(k):str(v) for k,v in api.info.items()};save()
        if (api.info.get('name')!=spec['name'] or int(api.info.get('number_of_real_parameters',-1))!=len(spec['real_parameters']) or int(api.info.get('number_of_complex_parameters',-1))!=len(spec['complex_parameters'])):raise ValueError('loaded native library parameter census differs')
        for p in c['points']:
            remaining();args=core.numerical_arguments(c,p);pr=c['precision']
            api.use_Qmc(transform='korobov3x3',epsrel=float(core.number(pr['epsrel'])),epsabs=args['epsabs_native'],
                        maxeval=pr['maxeval'],minn=pr['minn'],seed=pr['seed'],cputhreads=1,devices=[],errormode='all')
            row={'id':p['id'],'point':p,'raw':None,'derived':None,'status':'started'}
            state['rows'].append(row);state['calls_started']+=1;save()
            raw=api(real_parameters=args['real_parameters'],complex_parameters=[complex(*m) for m in args['complex_parameters']],
                    number_of_threads=1,number_of_presamples=10000,epsrel=float(core.number(pr['epsrel'])),epsabs=args['epsabs_native'],
                    maxeval=pr['maxeval'],wall_clock_limit=remaining(),errormode='all',format='series')
            # Separate write precedes the growing aggregate journal and parser.
            # A later aggregate cap/parse failure still retains this return.
            raw=list(raw);core.write(out/(p['id']+'.native-return.json'),{'id':p['id'],'point':p,'raw':raw})
            row['raw']=raw;row['status']='returned';state['calls_returned']+=1;save()
            row['derived']=core.derived(c,p,row['raw']);save()
        state['imports_after']=imports();state['platform_stdlib_imports_without_content_claim']=sorted(observed_system)
        if filepin(library)!=state['generated_library']:raise ValueError('generated loaded integral library changed')
        state['status']='returned';save()
    except BaseException as exc:
        state['status']='failed';state['error']=type(exc).__name__+': '+str(exc);save();raise

if __name__=='__main__':main(sys.argv[1])
