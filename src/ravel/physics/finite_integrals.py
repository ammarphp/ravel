"""Actual released pySecDec finite integral production through ordinary science.

No optional import or computation at planning. Common native-process ownership
contains code generation, single-job compilation and single-CPU QMC evaluation.
"""
import hashlib
import os
from pathlib import Path
import re
import shutil
from ravel.physics import model_tool_bridge as custody, finite_integrals_core as core
from ravel.workflow.state_io import atomic_json

SCOPE=core.SCOPE
API=Path(__file__).parents[1]/'data/finite_integrals/upstream-api.json'


def validate(task):
    core.keys(task,('config',),'finite integral task');core.text(task['config']);return task

def load(task,base):
    validate(task);p=custody._regular(task['config'],base);return p,core.config(core.read(p))

def runtime_tree(tree,base):
    core.keys(tree,('root','manifest'),'complete runtime tree')
    root=custody._regular(tree['root'],base,directory=True)
    manifest=custody._pin(tree['manifest'],base);doc=core.read(manifest)
    core.keys(doc,('schema_version','files'),'complete runtime manifest')
    if type(doc['schema_version']) is not int or doc['schema_version']!=1 or type(doc['files']) is not dict or not 1<=len(doc['files'])<=20000:
        raise ValueError('bounded nonempty complete runtime manifest required')
    actual={};members=[]
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('runtime aliases must be captured as ordinary snapshot files')
        if path.is_file():
            if len(members)>=20000:raise ValueError('runtime file census exceeds bound')
            actual[path.relative_to(root).as_posix()]=custody._hash(path);members.append(path)
        elif not path.is_dir():raise ValueError('nonregular runtime member')
    if actual!=doc['files']:raise ValueError('full runtime tree changed, including data/cache members')
    return root,manifest,members

def runtime(c,base):
    rt=c['runtime'];files=[];roots=[]
    for tree in rt['trees']:
        root,manifest,members=runtime_tree(tree,base);roots.append(root);files.extend([manifest,*members])
    if len(set(roots))!=len(roots) or any(a.is_relative_to(b) for a in roots for b in roots if a!=b):raise ValueError('disjoint exact runtime trees required')
    sites=[custody._regular(p,base,directory=True) for p in rt['site_roots']]
    contrib=custody._regular(rt['contrib_root'],base,directory=True)
    if any(not any(p==r or p.is_relative_to(r) for r in roots) for p in [*sites,contrib]):raise ValueError('runtime sites/contrib outside bound trees')
    packages=[p/'pySecDec' for p in sites if (p/'pySecDec').is_dir()]
    if len(packages)!=1:raise ValueError('exactly one pySecDec package required')
    api=core.read(API)
    for rel,sha in api['required_package_files'].items():
        p=packages[0]/rel
        if p not in files or custody._hash(custody._regular(p,base))!=sha:raise ValueError('runtime pySecDec source differs from inspected release: '+rel)
    tools={name:custody._pin(rt[name],base) for name in ('python','make','cxx')}
    paths=[custody._regular(v,base,directory=True) for v in rt['path']]
    for p in [*tools.values(),contrib,*paths]:
        if re.fullmatch(r'/[A-Za-z0-9_./+-]+',str(p)) is None:raise ValueError('tool/Make paths must be literal shell-safe ordinary paths')
    if any(not os.access(p,os.X_OK) for p in tools.values()):raise ValueError('executable runtime tools required')
    files.extend(tools.values())
    return sorted(set(files)),sites,contrib,tools,paths

def inputs(task,base):
    p,c=load(task,base);files,*_=runtime(c,p.parent)
    evidence=[*c['evidence'],*c.get('build_compatibility',{}).get('evidence',[])]
    return sorted(set([p,API,*files,*[custody._pin(x,p.parent) for x in evidence]]))

def execution_seconds(task,base):return load(task,base)[1]['max_seconds']

def source_output_policy(task,base):
    """Prospective ordinary policy for exact source-defined codegen stamps.

    No code generation, optional import or native execution. The producer file
    is already part of the complete runtime inputs; stamps are never results.
    Caller retains this explicit policy in the ordinary specification/approval.
    """
    p,c=load(task,base);files,sites,*_=runtime(c,p.parent)
    packages=[s/'pySecDec' for s in sites if (s/'pySecDec').is_dir()]
    source=packages[0]/'code_writer/templates/make_package/Makefile'
    expected=core.read(API)['required_package_files']['code_writer/templates/make_package/Makefile']
    if source not in files or custody._hash(source)!=expected:
        raise ValueError('exact admitted pySecDec sector producer source required')
    return {'schema_version':1,'allow_empty_directory_members':[{
        'path':'outputs/attempt-1/finite-integrals/native/finite_integral/finite_integral_integral/codegen',
        'role':'generated_build_marker_family','marker_class':'pysecdec166_sector_codegen_done',
        'source':{'path':str(source),'sha256':expected,'size':source.stat().st_size},'max_sectors':64}]}

def validate_scope(spec):
    policy=spec.get('review_policy',{}).get('policy',{});scopes=policy.get('claim_scopes',{})
    if (spec.get('schema_version')!=2 or spec.get('max_attempts')!=1 or policy.get('max_redos')!=0 or
        set(scopes)!={SCOPE} or scopes[SCOPE].get('actions')!=['delivery']):raise ValueError('finite integral provider needs one-attempt delivery-only ordinary review')
    return spec

def approved(task,out):
    from ravel.workflow import science
    for rd in (out,*out.parents):
        if (rd/'inputs/science-plan.json').is_file():
            plan=science.verify_worker(rd);spec=science.execution_spec(rd);validate_scope(spec)
            if spec['mode']!='finite-integrals' or spec['task']!=task or out!=(rd/plan['output_directory']/'finite-integrals').resolve():raise ValueError('finite integral worker task/output differs')
            return plan
    raise ValueError('approved ordinary finite integral worker required')

def identity(paths):
    answer={}
    for p in paths:
        p=custody._regular(p,Path.cwd());s=p.stat();answer[str(p)]=[custody._hash(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
    return answer

def census(out):
    rows=[]
    for p in sorted(out.rglob('*')):
        if p.is_symlink():raise ValueError('aliased provider output')
        if p.is_file():rows.append({'path':str(p.relative_to(out)),'bytes':p.stat().st_size,'sha256':custody._hash(p)})
    return rows

def run(task,base,output):
    out=Path(output).absolute();plan=approved(task,out);p,c=load(task,base)
    before=identity(inputs(task,base))
    if c['max_seconds']>plan['max_seconds']:raise ValueError('provider budget exceeds admitted science')
    if any(x.is_symlink() for x in (out,*out.parents)) or out.exists():raise ValueError('fresh regular output required')
    out.mkdir(parents=True);native=out/'native';native.mkdir()
    files,sites,contrib,tools,paths=runtime(c,p.parent)
    worker_source=custody._regular(Path(__file__).with_name('finite_integrals_worker.py'),Path.cwd())
    worker_sha256=custody._hash(worker_source)
    driver=native/'driver.py';shutil.copyfile(worker_source,driver)
    if custody._hash(custody._regular(driver,native))!=worker_sha256:raise ValueError('copied integral driver differs from exact source')
    req=native/'request.json';request={'config':c,'output':str(native),'ravel_source_root':str(Path(__file__).parents[2]),
       'sites':[str(s) for s in sites],'contrib_root':str(contrib),'make':str(tools['make']),'cxx':str(tools['cxx']),
       'path':':'.join(str(q) for q in paths),'runtime_assets':{str(q):custody._hash(q) for q in files},
       'driver':{'path':str(driver),'sha256':worker_sha256}}
    request['runtime_assets'][str(driver)]=worker_sha256
    core.write(req,request);selected=identity([driver,req])
    atomic_json(out/'input-custody.json',{'files':before,'selected':selected,'configuration':c})
    from ravel.physics.reinterpret_db import execute_native
    errors=[];receipt=None;delivery=None;precision=None
    try:receipt=execute_native([str(tools['python']),'-I','-B',str(driver),str(req)],native,c)
    except (ValueError,OSError,RuntimeError) as exc:errors.append('native execution: '+str(exc))
    raw=census(native);atomic_json(out/'raw-census.json',{'files':raw,'before_adjudication':True})
    try:
        delivery=core.read(native/'native-integrals.json');precision=core.delivery_check(c,delivery)
        if sum(q['bytes'] for q in raw)>c['max_output_bytes']:raise ValueError('retained native storage exceeds declared postcondition')
        lib=delivery['generated_library'];q=custody._regular(lib['path'],native)
        if not q.is_relative_to(native) or custody._hash(q)!=lib['sha256'] or q.stat().st_size!=lib['bytes']:raise ValueError('generated library output pin differs')
        for key in ('imports_before','imports_after'):
            custody.imported_sources([{'path':r['path'],'sha256':r['sha256']} for r in delivery[key]],request['runtime_assets'])
        if not precision:errors.append('returned QMC error estimates exceed requested component targets')
    except (ValueError,OSError,KeyError,TypeError) as exc:errors.append('ending provider delivery: '+str(exc))
    try:
        if before!=identity(inputs(task,base)) or selected!=identity([driver,req]):raise ValueError('input/runtime/selected bytes changed')
    except (ValueError,OSError,KeyError,TypeError) as exc:errors.append('unconditional ending input custody: '+str(exc))
    result={'status':'failed' if errors else 'passed','status_scope':SCOPE,'physics_validated':False,'backend':'pySecDec','version':core.VERSION,
        'configuration':c,'delivery':delivery,'native_execution':receipt,'errors':errors,'estimated_precision_met':precision,
        'qualified_enclosure':False,'numerical_qualification':'unknown','oracle_independence_proven':False,
        'operation_resources':c['operation_resources'],'automatic_redo':False,
        'limitations':['QMC component errors are estimates, not rigorous error bounds or coverage probabilities.',
            'Fixed binary64 integration with requested stopping precision, not arbitrary precision.',
            'Only finite massive triangle/box epsilon-zero coefficients in proven nonzero-F regimes.',
            'Complex pole masses are supplied physical/convention inputs; no width or i0 regulator is inferred.',
            'No UV matching, Wilson coefficients, amplitudes, cross sections or automatic EFT/source-function identification.',
            'Runtime source/binary pins are not a complete OS loader trace; system execution dependencies remain qualification obligations.',
            'Output storage ceiling is checked at completion; time/RAM use the common sampled native owner.',
            'Top-level integral calls are counted; maxeval is an upstream requested budget, not an OS-enforced hard integrand-call quota.']}
    raw_after=census(native)
    if raw_after!=raw:result['errors'].append('native outputs changed during ending checks');result['status']='failed'
    # Bind every pre-existing output, including progressive failure evidence.
    initial=census(out)
    expected={row['path']:row['sha256'] for row in initial}
    committed=[]
    if result['status']=='passed':
        expected['reported-values.json']=core.write(out/'reported-values.json',core.reference_document(c,delivery))
        committed.append('reported-values.json')
    expected['finite-integrals.json']=core.write(out/'finite-integrals.json',result)
    ending=census(out)
    if any(custody._hash(out/name)!=sha for name,sha in expected.items()) or {r['path'] for r in ending}!=set(expected):
        failed={**result,'status':'failed','errors':[*result['errors'],'ending output bytes changed; originals retained']}
        core.write(out/'delivery-failure.json',failed);return failed
    if sum(row['bytes'] for row in ending)>c['max_output_bytes']:
        result['errors'].append('whole retained output exceeds storage postcondition');result['status']='failed'
        # Only our still-identical fresh completion may be replaced. Raw evidence
        # and the reported-value derivative remain retained, uncommitted outputs.
        result['uncommitted_derivatives']=committed
        expected['finite-integrals.json']=core.write(out/'finite-integrals.json',result)
    if any(custody._hash(out/name)!=sha for name,sha in expected.items()) or {r['path'] for r in census(out)}!=set(expected):
        failed={**result,'status':'failed','errors':[*result['errors'],'final output bytes changed; originals retained']}
        core.write(out/'delivery-failure.json',failed);return failed
    return result

def context_inputs(task,base):
    p,c=load(task,base)
    evidence=[*c['evidence'],*c.get('build_compatibility',{}).get('evidence',[])]
    return [p,API,*[custody._pin(x,p.parent) for x in evidence]]

def context(task,base):
    p,c=load(task,base)
    return {'schema_version':1,'mode':'finite-integrals','operation':'generate_compile_evaluate_finite_scalar_integral',
            'configuration':{k:v for k,v in c.items() if k!='runtime'},'generator_spec':core.generator_spec(c),
            'runtime_version':core.VERSION,'ordinary_task':{'config':str(p)},'execution_authorized':False,'physics_validated':False,
            'dependency_pins':[{'path':str(q),'sha256':custody._hash(q)} for q in context_inputs(task,base)]}
