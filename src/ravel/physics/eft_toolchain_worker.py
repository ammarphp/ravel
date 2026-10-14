"""Ordinary child entry point; no optional scientific imports at module import."""
import hashlib
import importlib.metadata
import importlib.util
import os
from pathlib import Path
import sys
import sysconfig


def hash_file(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def check(files):
    for name,sha in files.items():
        p=Path(name)
        if any(x.is_symlink() for x in (p,*p.parents)) or not p.is_file() or hash_file(p)!=sha:raise ValueError('dependency changed: '+name)

def imports(request):
    std=Path(sysconfig.get_path('stdlib')).resolve();sites=[Path(s) for s in request['sites']]
    allowed={**request['runtime_assets'],**request['selected_files']};seen={}
    for name,module in list(sys.modules.items()):
        raw=getattr(module,'__file__',None)
        if not raw:continue
        p=Path(raw).absolute()
        if p.is_relative_to(std) and not any(p.is_relative_to(s) for s in sites) and 'site-packages' not in p.parts:continue
        if allowed.get(str(p))!=hash_file(p):raise ValueError('unadmitted Python import: '+str(p))
        seen[name]={'path':str(p),'sha256':allowed[str(p)]}
    return seen

def census(request):
    """Current files of every admitted top-level runtime entry, without caches."""
    sites=[Path(s) for s in request['sites']];tops=set()
    for name in request['runtime_assets']:
        p=Path(name)
        for site in sites:
            if p.is_relative_to(site):tops.add(site/p.relative_to(site).parts[0]);break
        else:raise ValueError('runtime asset outside declared sites: '+name)
    actual=set()
    for top in tops:
        if top.is_file():actual.add(str(top));continue
        for p in top.rglob('*'):
            if '__pycache__' not in p.relative_to(top).parts and p.is_file():actual.add(str(p))
    return actual

def main(argv=None):
    if sys.flags.optimize:raise ValueError('optimized Python is not supported by upstream assertions')
    args=sys.argv[1:] if argv is None else argv
    if len(args)!=1:raise ValueError('one request required')
    source=Path(__file__).with_name('eft_toolchain_core.py')
    spec=importlib.util.spec_from_file_location('eft_toolchain_core',source);core=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=core;spec.loader.exec_module(core)
    req=core.read_json(Path(args[0]));c=core.config(req['config']);out=Path(req['output'])
    journal=core.Journal(out/'progress.json',c['max_export_bytes'])
    try:
        journal.retain('runtime_process',{'python_version':sys.version,'python_executable':sys.executable,
            'pid':os.getpid(),'platform':sys.platform,'stdlib_outside_declared_sites':'allowed_not_individually_rehashed'})
        check(req['selected_files']);check(req['runtime_assets'])
        if req['selected_files'].get(str(Path(__file__).absolute()))!=hash_file(__file__):raise ValueError('worker source mismatch')
        for pkg,root in req['package_roots'].items():
            check({str(Path(root)/rel):sha for rel,sha in req['required_package_files'][pkg].items()})
        sys.path[:0]=req['sites']
        versions={name:importlib.metadata.version(name) for name in c['runtime']['versions']}
        journal.retain('runtime_versions',versions)
        if versions!=c['runtime']['versions']:raise ValueError('runtime version mismatch')
        import wilson
        import numpy as np
        flavio=None;smelli=None
        if c['observables'] or c['smelli'] is not None:import flavio
        if c['smelli'] is not None:import smelli
        journal.retain('initial_imports',imports(req))
        result=core.evaluate(c,req['point'],req['cache'],wilson,flavio,smelli,np,journal,out)
        journal.retain('completed_quantities',result)
        journal.retain('final_imports',imports(req));check(req['selected_files']);check(req['runtime_assets'])
        # End with a fresh complete census, including newly created unexpected files.
        if census(req)!=set(req['runtime_assets']):raise ValueError('ending runtime census changed')
        journal.value['status']='completed';journal.save();return 0
    except BaseException as exc:
        journal.value['status']='failed';journal.value['error']=type(exc).__name__+': '+str(exc);journal.save();raise

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(2)
