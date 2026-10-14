"""Ordinary EFT running, matching and fixed precision predictions.

Planning imports no upstream scientific package. The existing ordinary science
worker and native-process runner own execution, time/RAM and cleanup.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from ravel.physics import model_tool_bridge as custody, eft_toolchain_core as core
from ravel.workflow.state_io import atomic_json

SCOPE=core.SCOPE
API=Path(__file__).parents[1]/'data/eft_toolchain/upstream-api.json'

def validate(task):
    core.keys(task,('config',),'EFT toolchain task');core.text(task['config'],'config path');return task

def load(task,base):
    validate(task);p=custody._regular(task['config'],base)
    return p,core.config(core.read_json(p))

def package_roots(c,base):
    sites=[custody._regular(s,base,directory=True) for s in c['runtime']['site_roots']]
    packages=['wilson']
    if c['observables'] or c['smelli'] is not None:packages.append('flavio')
    if c['smelli'] is not None:packages.append('smelli')
    answer={}
    for name in packages:
        found=[site/name for site in sites if (site/name).is_dir()]
        if len(found)!=1:raise ValueError('exactly one admitted '+name+' package required')
        answer[name]=custody._regular(found[0],base,directory=True)
    return sites,answer

def _norm(name):return re.sub(r'[-_.]+','-',name).lower()

def distribution_closure(sites,names):
    """Installed dependency closure from distribution metadata; nothing is imported.

    Extras are excluded. A conditional dependency that is not installed is
    treated as inactive; an unconditional one must be installed in the sites.
    """
    import importlib.metadata as md
    found={}
    for site in sites:
        for d in md.distributions(path=[str(site)]):
            key=_norm(d.metadata['Name'] or '')
            if not key:raise ValueError('installed distribution without a name in '+str(site))
            if key in found:raise ValueError('duplicate installed distribution: '+key)
            found[key]=(Path(site),d)
    closure={};stack=[_norm(n) for n in names]
    while stack:
        key=stack.pop()
        if key in closure:continue
        if key not in found:raise ValueError('required distribution is not installed in the declared sites: '+key)
        closure[key]=found[key]
        for requirement in found[key][1].requires or []:
            spec,_,marker=requirement.partition(';')
            if re.search(r'\bextra\s*==',marker):continue
            match=re.match(r'\s*([A-Za-z0-9][A-Za-z0-9._-]*)',spec)
            if match is None:raise ValueError('unparsed dependency declaration: '+requirement)
            dep=_norm(match.group(1))
            if dep in found:stack.append(dep)
            elif not marker.strip():raise ValueError('declared dependency is not installed: '+key+' requires '+dep)
    return closure

def _census_files(top):
    if top.is_symlink():raise ValueError('runtime tree contains symlink: '+str(top))
    if top.is_file():return [top]
    files=[]
    for p in top.rglob('*'):
        if '__pycache__' in p.relative_to(top).parts:continue
        if p.is_symlink():raise ValueError('runtime tree contains symlink: '+str(p))
        if p.is_file():files.append(p)
    return files

def _recorded(d):
    """Every RECORD entry; importlib.metadata.files silently drops missing files."""
    import csv
    text=d.read_text('RECORD')
    if text is None:raise ValueError('installed distribution without RECORD: '+str(d.metadata['Name']))
    return [row[0] for row in csv.reader(text.splitlines()) if row and row[0]]

def startup_distributions(sites):
    """Distributions that install a site .pth file; the interpreter runs those at startup."""
    import importlib.metadata as md
    owners=[]
    for site in sites:
        for d in md.distributions(path=[str(site)]):
            if any(len(Path(e).parts)==1 and e.endswith('.pth') for e in _recorded(d)):owners.append(d.metadata['Name'])
    return owners

def runtime_census(sites,names):
    """Exact files of the installed dependency closure of the named packages.

    Every top-level module, package and metadata directory recorded by a closure
    distribution is censused in full, so an unrecorded planted file is a change.
    Bytecode caches are excluded; the worker reads none (empty pycache prefix).
    """
    closure=distribution_closure(sites,list(names)+startup_distributions(sites));tops=set()
    for key,(site,d) in closure.items():
        for entry in _recorded(d):
            parts=Path(entry).parts
            if not parts or '..' in parts or '__pycache__' in parts or Path(entry).is_absolute():continue
            p=site/entry
            if not p.is_file():raise ValueError('recorded installed file is missing: '+str(p))
            tops.add(site/parts[0])
    files=sorted({p for top in tops for p in _census_files(top)})
    return files,{key:d.version for key,(site,d) in sorted(closure.items())}

def runtime_block(python,sites,names):
    """Runtime declaration for the exact installed closure of the named packages."""
    sites=[Path(s).absolute() for s in sites]
    files,versions=runtime_census(sites,names)
    return {'python':{'path':str(Path(python).absolute()),'sha256':custody._hash(python)},
            'site_roots':[str(s) for s in sites],
            'assets':[{'path':str(p),'sha256':custody._hash(p)} for p in files],'versions':versions}

def release_api(sites,names=('wilson','flavio','smelli')):
    """Reviewed release census of the scientific packages in their installed wheels."""
    closure=distribution_closure(sites,names);answer={'schema_version':2,
        'scope':'reviewed released-wheel API epoch; native numerical qualification separate',
        'releases':{},'required_package_files':{}}
    for name in names:
        site,d=closure[_norm(name)];answer['releases'][name]=d.version;rows={}
        for entry in _recorded(d):
            parts=Path(entry).parts
            if len(parts)<2 or parts[0]!=name or '__pycache__' in parts:continue
            rows[Path(*parts[1:]).as_posix()]=custody._hash(site/entry)
        if not rows:raise ValueError('no recorded package files for '+name)
        answer['required_package_files'][name]=dict(sorted(rows.items()))
    return answer

def runtime_files(c,base):
    rt=c['runtime'];assets=[custody._pin(p,base) for p in rt['assets']]
    if len(set(assets))!=len(assets):raise ValueError('duplicate runtime member')
    sites,roots=package_roots(c,base)
    expected,versions=runtime_census(sites,list(roots))
    if set(assets)!=set(expected):raise ValueError('runtime assets must equal the complete installed dependency closure census')
    api=core.read_json(API)
    for name in roots:
        if versions.get(_norm(name))!=api['releases'].get(name):
            raise ValueError('installed '+name+' '+str(versions.get(_norm(name)))+' differs from the reviewed release '+str(api['releases'].get(name)))
    for name,version in rt['versions'].items():
        if versions.get(_norm(name))!=version:raise ValueError('declared runtime version differs from the installed distribution: '+name)
    required=api['required_package_files']
    pins={str(custody._regular(p['path'],base)):p['sha256'] for p in rt['assets']}
    for name,root in roots.items():
        for rel,sha in required[name].items():
            if pins.get(str(root/rel))!=sha:raise ValueError('runtime source differs from inspected API: '+name+'/'+rel)
    return assets,sites,roots

def inputs(task,base):
    p,c=load(task,base);base=p.parent
    point=custody._pin(c['wcxf'],base);core.wc_document(core.read_json(point))
    runtime,sites,roots=runtime_files(c,base)
    python=custody._pin(c['runtime']['python'],base)
    if not os.access(python,os.X_OK):raise ValueError('runtime interpreter not executable')
    extras=[custody._pin(pin,base) for pin in c['conventions']['evidence']]
    if c['smelli'] is not None:
        cache=custody._pin(c['smelli']['covariance_cache'],base);core.cache_document(core.read_json(cache));extras.append(cache)
    return sorted(set([p,point,python,API,*runtime,*extras]))

def execution_seconds(task,base):return load(task,base)[1]['max_seconds']

def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if (spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or
        set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']):
        raise ValueError('EFT toolchain requires one-attempt delivery-only ordinary review')
    return spec

def approved(task,out):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            if spec['mode']!='eft-toolchain' or spec['task']!=task or out!=(rd/plan['output_directory']).resolve():raise ValueError('EFT worker binding differs')
            return plan
    raise ValueError('approved ordinary EFT worker required')

def identity(paths):
    answer={}
    for path in paths:
        p=custody._regular(path,Path.cwd());s=p.stat()
        answer[str(p)]=[custody._hash(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
    return answer

def run(task,base,output):
    out=Path(output).absolute();plan=approved(task,out);p,c=load(task,base)
    paths=inputs(task,base);before=identity(paths)
    if c['max_seconds']>plan['max_seconds']:raise ValueError('native time exceeds admitted stage')
    if any(x.is_symlink() for x in (out,*out.parents)):raise ValueError('aliased output root')
    out.mkdir(parents=True,exist_ok=True);native=out/'eft-native';native.mkdir(exist_ok=False)
    _,sites,roots=runtime_files(c,p.parent)
    driver=native/'driver.py';shutil.copyfile(Path(__file__).with_name('eft_toolchain_worker.py'),driver)
    serializer=native/'eft_toolchain_core.py';shutil.copyfile(Path(core.__file__),serializer)
    point=core.read_json(custody._pin(c['wcxf'],p.parent))
    cache=None if c['smelli'] is None else core.read_json(custody._pin(c['smelli']['covariance_cache'],p.parent))
    request={'config':c,'point':point,'cache':cache,'output':str(native),'sites':[str(s) for s in sites],
        'package_roots':{k:str(v) for k,v in roots.items()},'runtime_assets':{str(custody._pin(pin,p.parent)):pin['sha256'] for pin in c['runtime']['assets']},
        'selected_files':{str(q):custody._hash(q) for q in (driver,serializer)},
        'required_package_files':core.read_json(API)['required_package_files']}
    req=native/'request.json';core.write_json(req,request);selected=identity([driver,serializer,req])
    atomic_json(out/'eft-input-custody.json',{'inputs':before,'source':c['source'],'conventions':c['conventions'],'physics_validated':False})
    from ravel.physics.reinterpret_db import execute_native
    errors=[];receipt=None
    empty=native/'pycache-prefix';empty.mkdir()
    try:receipt=execute_native([str(custody._pin(c['runtime']['python'],p.parent)),'-I','-B','-X','pycache_prefix='+str(empty),str(driver),str(req)],native,c)
    except (ValueError,OSError,RuntimeError) as exc:errors.append('native execution: '+str(exc))
    raw=[]
    for q in sorted(native.rglob('*')):
        if q.is_symlink():errors.append('aliased output: '+str(q));continue
        if q.is_file():raw.append({'path':str(q.relative_to(out)),'bytes':q.stat().st_size,'sha256':custody._hash(q)})
    atomic_json(out/'eft-raw-census.json',{'files':raw,'before_semantic_adjudication':True})
    delivery=None
    try:
        delivery=core.read_json(native/'progress.json',c['max_export_bytes'])
        core.delivery_check(delivery,c,point)
        if before!=identity(inputs(task,base)) or selected!=identity([driver,serializer,req]):raise ValueError('input/runtime/worker bytes changed')
        if sum(r['bytes'] for r in raw)>8*c['max_export_bytes']:raise ValueError('whole native export storage exceeds declared derived cap')
    except (ValueError,OSError,KeyError,TypeError) as exc:errors.append('ending EFT custody/result: '+str(exc))
    result={'status':'failed' if errors else 'passed','status_scope':SCOPE,'physics_validated':False,
        'source':c['source'],'conventions':c['conventions'],'delivery':delivery,'native_execution':receipt,
        'errors':errors,'automatic_redo':False,'eft_applicability':'unknown','numerical_qualification':'unknown',
        'coverage_calibration':'unknown','interval_qualification':'unknown','scope':'Native fixed coefficient running/matching, observable and selected likelihood delivery',
        'limitations':['No optimizer, CLs, confidence interval or general physical matching certificate.',
            'Wilson/RGE and observable internal evaluation counts are not instrumented.',
            'Supplied smelli covariance provenance and cross-domain independence require scientific review.',
            'Complete Python/runtime asset custody is not an OS loaded-library trace.']}
    atomic_json(out/'eft-toolchain.json',result);return result

def context_inputs(task,base):
    p,c=load(task,base);extra=[custody._pin(c['wcxf'],p.parent),API]
    extra.extend(custody._pin(pin,p.parent) for pin in c['conventions']['evidence'])
    if c['smelli'] is not None:extra.append(custody._pin(c['smelli']['covariance_cache'],p.parent))
    return sorted(set([p,*extra]))

def context(task,base):
    p,c=load(task,base);point=core.wc_document(core.read_json(custody._pin(c['wcxf'],p.parent)))
    scientific={k:v for k,v in c.items() if k!='runtime'}
    return {'schema_version':1,'mode':'eft-toolchain','operation':'source_bound_fixed_point_chain',
        'scientific_config':scientific,'input_wcxf':point,
        'runtime_declaration':{'python':c['runtime']['python'],'versions':c['runtime']['versions'],
            'asset_count':len(c['runtime']['assets']),'actual_runtime_preflight':'not_performed_by_context'},
        'dependencies':[{'path':str(q),'sha256':custody._hash(q)} for q in context_inputs(task,base)],
        'upstream_releases':core.read_json(API)['releases'],'ordinary_task':{'config':str(p)},'execution_authorized':False,
        'physics_validated':False,'next':'materialize ordinary one-attempt delivery study; bind independent numerical/physics checks separately',
        'excluded_inferences':['SFitter/WCxf basis equivalence','automatic collider/flavour likelihood combination','CLs','physical matching validity']}


def main(argv=None):
    """Write the runtime declaration or the reviewed release census from installed sites."""
    p=argparse.ArgumentParser(prog='python -m ravel.physics.eft_toolchain')
    sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('runtime',help='runtime block for a config: python, site roots, closure assets, versions')
    r.add_argument('--python',default=sys.executable);r.add_argument('--site',action='append',required=True)
    r.add_argument('--package',action='append',choices=('wilson','flavio','smelli'),required=True)
    r.add_argument('--out',required=True)
    a=sub.add_parser('api',help='maintainer census of the reviewed released wheels')
    a.add_argument('--site',action='append',required=True);a.add_argument('--out',required=True)
    args=p.parse_args(argv)
    sites=[Path(s).absolute() for s in args.site]
    value=runtime_block(Path(args.python).absolute(),sites,args.package) if args.command=='runtime' else release_api(sites)
    Path(args.out).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
