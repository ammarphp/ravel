"""CheckMATE2.5.2 supplied-event Fritz build via the ordinary routine-build API.

Only the released non-Pythia translation units are compiled. The existing ROOT,
Delphes and analyses libraries remain pinned dependencies. No configure, download,
analysis-library rebuild, event processing or statistical inference occurs here.
Planning reads bytes only; ordinary science owns approval, supervision and review.
"""
from pathlib import Path
import hashlib, json, os, re, shutil, time
from ravel.workflow.state_io import atomic_json, read_json
from ravel.physics import checkmate_252_compat as compat
from ravel.physics import routine_build as rb
from ravel.workflow import science

KIND='checkmate252-supplied-fritz-build'
AM_SHA='dd2207db71a92277d59e530549618c012713c1289500fbf1d60dc7d74a9b1f25'
# Compile/link directly to one executable; -g0 deliberately disables debug
# information so Darwin's driver does not add a dsymutil bundle action. The
# source-prefix census remains closed; unexpected sidecars still refuse.
FLAGS=['-std=c++20','-stdlib=libc++','-pthread','-g0','-O2','-Wno-c++11-narrowing']
RECIPE={'workers':1,'max_seconds':660,'build_seconds':600,'probe_seconds':15,
        'max_ram_mib':4096,'max_output_bytes':536870912,'max_attempts':1}
ENV_KEYS={'PATH','SDKROOT','LC_ALL','LC_CTYPE','PYTHONUTF8','PYTHONCOERCECLOCALE',
          'OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'}

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def bound(value):
    if type(value) is not dict or set(value)!={'path','sha256'}:
        raise ValueError('exact file pin required')
    path=Path(value['path']).absolute()
    if not path.is_file() or digest(path)!=value['sha256']:
        raise ValueError('source/runtime bytes changed: '+str(path))
    return path

def file_fact(path,relative=None):
    path=Path(path)
    fact={'path':str(path.absolute()),'sha256':digest(path)}
    if relative is not None:fact.update(relative=relative,size=path.stat().st_size)
    return fact

def units(text):
    if text.count('fritz_SOURCES =')!=1 or text.count('if HAVE_PYTHIA')!=1:
        raise ValueError('released conditional source boundary required')
    before=text.split('fritz_SOURCES =',1)[1].split('fritz_LDADD =',1)[0]
    result=re.findall(r'\b[^\s]+\.cc\b',before)
    if len(result)!=21 or len(set(result))!=21 or any('pythiahandler' in x for x in result):
        raise ValueError('complete21 distinct released non-Pythia units required')
    return ['tools/fritz/'+x for x in result]

def _relative(value):
    p=Path(value)
    if p.is_absolute() or '..' in p.parts or not p.parts:
        raise ValueError('safe source-relative member required')
    return p

def _inventory(pin):
    path=bound(pin); inv=read_json(path)
    if (type(inv) is not dict or set(inv)!={'schema_version','kind','original_root','revision','files'}
            or inv['schema_version']!=1 or inv['kind']!='checkmate252-preserved-prefix-source'
            or inv['revision']!=compat.REVISION or type(inv['files']) is not list or not inv['files']):
        raise ValueError('exact preserved2.5.2 source inventory required')
    root=compat.original(inv['original_root']); files=[]; seen=set()
    for row in inv['files']:
        if type(row) is not dict or set(row)!={'relative','sha256','size','mode','link'}:
            raise ValueError('complete source byte/mode row required')
        rel=_relative(row['relative']); p=root/rel
        if rel.as_posix() in seen or any(q.is_symlink() for q in p.parents if q.is_relative_to(root)):
            raise ValueError('duplicate or linked source member')
        if (os.readlink(p) if p.is_symlink() else None)!=row['link'] or not p.resolve().is_relative_to(root):
            raise ValueError('source leaf alias differs or escapes prefix')
        seen.add(rel.as_posix())
        bound({'path':str(p),'sha256':row['sha256']})
        if p.stat().st_size!=row['size'] or (p.stat().st_mode&0o777)!=row['mode']:
            raise ValueError('source mode/size differs')
        if row['size']==0 and rel.as_posix()!='NEWS':
            raise ValueError('unreviewed empty installed-source member')
        files.append(p)
    if digest(root/'tools/fritz/Makefile.am')!=AM_SHA:
        raise ValueError('released Fritz source selector differs')
    selected=units((root/'tools/fritz/Makefile.am').read_text())
    if not set(selected+['VERSION','COPYING','bin/CheckMATE',*compat.ORIGINALS])<=seen:
        raise ValueError('source inventory omits source/entry/license obligations')
    if any(str(p.resolve().relative_to(root)) not in seen for p in files if p.is_symlink()):
        raise ValueError('source alias target omitted')
    return inv,root,selected,files

def include_members(root,selections=('.',)):
    """Include spelling and resolved bytes, including configured directory aliases."""
    root=Path(root).absolute(); result=[]
    def walk(directory, ancestors):
        real=directory.resolve()
        if real in ancestors:raise ValueError('include directory alias cycle')
        for child in sorted(directory.iterdir()):
            if child.is_dir():walk(child,ancestors|{real})
            elif child.is_file():
                result.append(child)
                if len(result)>50000:raise ValueError('include census exceeds bounded member ceiling')
            else:raise ValueError('nonregular include member')
    if (type(selections) not in (list,tuple) or not selections
            or any(type(x) is not str for x in selections) or len(set(selections))!=len(selections)):
        raise ValueError('explicit distinct include selections required')
    paths=[root if x=='.' else root/_relative(x) for x in selections]
    if any(a!=b and a.is_relative_to(b) for a in paths for b in paths):
        raise ValueError('overlapping include selections')
    for selected in paths:walk(selected,set())
    return result

def _headers(value):
    path=bound(value); j=read_json(path)
    if type(j) is not dict or set(j)!={'root','selections','files'} or type(j['files']) is not list or not j['files']:
        raise ValueError('complete declared include-root census required')
    root=Path(j['root']).absolute(); expected={}; files=[]
    for row in j['files']:
        if type(row) is not dict or set(row)!={'relative','resolved','sha256','link'}:
            raise ValueError('include member identity required')
        rel=_relative(row['relative']); p=root/rel
        if str(rel) in expected:raise ValueError('duplicate include member')
        expected[str(rel)]=row
        if str(p.resolve())!=row['resolved'] or (os.readlink(p) if p.is_symlink() else None)!=row['link']:
            raise ValueError('include alias changed')
        files.append(bound({'path':str(p.resolve()),'sha256':row['sha256']}))
    actual={str(p.relative_to(root)) for p in include_members(root,j['selections'])}
    if actual!=set(expected):raise ValueError('include population added/removed')
    return root,[path,*files]

def configuration(task,base):
    rb.validate(task); cp=science.regular(task['input'],base); c=read_json(cp)
    if (type(c) is not dict or set(c)!={'schema_version','kind','source_inventory','profile','recipe'}
            or type(c['schema_version']) is not int or c['schema_version']!=5
            or c['kind']!=KIND or c['recipe']!=RECIPE
            or any(type(c['recipe'].get(k)) is not int for k in RECIPE)):
        raise ValueError('closed supplied-event Fritz build configuration required')
    inv,root,selected,files=_inventory(c['source_inventory'])
    pp=bound(c['profile']); p=read_json(pp)
    keys={'compiler','compiler_identity','env_tool','environment','include_censuses','libraries',
          'rpaths','root_makefile','root_aux_cflags','scope','runtime_artifacts'}
    if type(p) is not dict or set(p)!=keys or p['scope']!='supplied-event-only;no-pythia-generation-or-shower':
        raise ValueError('explicit supplied-only profile required')
    compiler=bound(p['compiler']); identity=rb.executable_identity(compiler)
    if identity!=p['compiler_identity']:raise ValueError('compiler alias/target changed')
    envtool=bound(p['env_tool'])
    if envtool!=Path('/usr/bin/env'):raise ValueError('fixed system environment launcher required')
    environment=p['environment']
    if (type(environment) is not dict or set(environment)!=ENV_KEYS
            or any(type(v) is not str or '\0' in v for v in environment.values())
            or any(environment[k]!='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'))):
        raise ValueError('closed one-worker compile environment required')
    if not Path(environment['SDKROOT']).is_dir():raise ValueError('declared existing SDK missing')
    if type(p['scope']) is not str:raise ValueError('literal profile scope required')
    makefile=bound(p['root_makefile']); text=makefile.read_text()
    aux=re.search(r'^ROOTAUXCFLAGS = (.*)$',text,re.M)
    if not aux or aux[1]!=p['root_aux_cflags'] or '-std=c++20' not in aux[1]:
        raise ValueError('ROOT declaredC++20 convention differs')
    includes=[]
    if type(p['include_censuses']) is not list or not p['include_censuses']:
        raise ValueError('external header census required')
    for value in p['include_censuses']:
        r,f=_headers(value); includes.append(r);files.extend(f)
    if type(p['libraries']) is not list or not p['libraries'] or len(p['libraries'])>40:
        raise ValueError('closed library denominator required')
    libraries=[bound(x) for x in p['libraries']]
    if len(set(x.resolve() for x in libraries))!=len(libraries):raise ValueError('duplicate library')
    if any('/py82/' in str(x) or x.name=='libpythia8.dylib' for x in libraries):
        raise ValueError('Fritz must not link either Pythia library directly')
    if not {'libDelphes.dylib','libanalyses.dylib'}<={x.name for x in libraries}:
        raise ValueError('existing Delphes/analyses dependencies required')
    if type(p['runtime_artifacts']) is not list or not p['runtime_artifacts']:
        raise ValueError('declared transitive runtime artifacts required')
    runtime_artifacts=[bound(x) for x in p['runtime_artifacts']]
    if len(set(x.resolve() for x in runtime_artifacts))!=len(runtime_artifacts):
        raise ValueError('duplicate runtime artifact')
    if (type(p['rpaths']) is not list or not p['rpaths']
            or any(type(x) is not str or not re.fullmatch(r'/[A-Za-z0-9_./-]+',x) or not Path(x).is_dir() for x in p['rpaths'])):
        raise ValueError('literal existing runtime library directories required')
    files += [cp,pp,bound(c['source_inventory']),compiler.resolve(),envtool,makefile,*libraries,*runtime_artifacts]
    return c,inv,p,selected,sorted(set(x.resolve() for x in files)),includes,libraries

def inputs(task,base):return configuration(task,base)[4]
def execution_seconds(task,base):return configuration(task,base)[0]['recipe']['max_seconds']

def source_output_policy(task, base):
    """Prospective policy for literal upstream metadata copies, not results.

    Put this in the original version2 science specification before planning.
    The ordinary plan/approval binds both singleton inputs and every destination.
    This never changes an existing run or certifies upstream JSON semantics.
    """
    c, inv, *_ = configuration(task, base)
    inventory = Path(c['source_inventory']['path']).resolve()
    inventory_pin = {'path': str(inventory), 'sha256': digest(inventory), 'size': inventory.stat().st_size}
    rows = []
    for row in inv['files']:
        relative = row['relative']
        if relative.startswith('data/') and relative.endswith('.json'):
            rows.append({'path': 'outputs/attempt-1/prefix/' + relative,
                         'role': 'checkmate252_prefix_source', 'relative': relative,
                         'inventory': dict(inventory_pin),
                         'source': {'path': inv['original_root'] + '/' + relative, 'sha256': row['sha256'], 'size': row['size']}})
    return {'schema_version': 2, 'allow_empty_directory_members': [], 'verbatim_input_source_copies': rows}

def build_plan(task,base,out):
    c,inv,p,selected,files,includes,libraries=configuration(task,base)
    out=Path(out).absolute(); prefix=out/'prefix'; binary=prefix/'tools/fritz/bin/fritz'
    include_dirs=['tools/fritz/include/global','tools/fritz/include/fritz','tools/fritz/include/delpheshandler',
                  'tools/fritz/include/analysishandler','tools/analysis/include/base','tools/analysis/include/kinematics',
                  'tools/analysis/include/kinematics/mctlib','tools/analysis/include/kinematics/mt2family',
                  'tools/analysis/include/kinematics/topness']
    include_dirs += ['tools/analysis/include/analyses/'+x for x in
        ('ATLAS_7TeV','ATLAS_8TeV','ATLAS_13TeV','ATLAS_14TeV_HighLumi','CMS_7TeV','CMS_8TeV','CMS_13TeV','CMS_14TeV_HighLumi')]
    # Released Makefile contains an absent, unused CMS14 include directory.
    # Preserve its literal -I selection, disclose it, and let real compilation
    # establish whether every referenced header is available.
    missing_include_dirs=[x for x in include_dirs if not (Path(inv['original_root'])/x).is_dir()]
    if any(x in include_dirs[:9] for x in missing_include_dirs):
        raise ValueError('required common released include layout missing')
    env=[str(p['env_tool']['path']),'-i',*[k+'='+v for k,v in sorted(p['environment'].items())]]
    command=[*env,p['compiler']['path'],*FLAGS,*['-I'+str(x) for x in includes],
             *['-I'+str(prefix/x) for x in include_dirs],*[str(prefix/x) for x in selected],
             *[str(x.resolve()) for x in libraries],*['-Wl,-rpath,'+x for x in p['rpaths']],'-o',str(binary)]
    return {'schema_version':5,'kind':'routine-build-plan','framework':'checkmate-supplied-fritz',
            'task':dict(task),'config':c,'source_inventory':inv,'profile':p,'prefix':str(prefix),
            'binary':str(binary.relative_to(out)),'command':command,
            'probe_command':[*env,str(binary),str(out/'zero-event-loader.ini')],
            'inputs':[str(x) for x in files],'compute_authorized':False,'physics_validated':False,
            'absent_configured_include_directories':missing_include_dirs,
            'operational_prefix_derivative':{
                'materialized_contained_aliases':[f['relative'] for f in inv['files'] if f['link'] is not None],
                'omitted_empty_nonruntime_documents':[f['relative'] for f in inv['files'] if f['size']==0 and f['relative']=='NEWS'],
                'policy':'Source/card bytes and original alias/document facts retained; regular files for ordinary output snapshot.'},
            'scope':'Complete21-unit supplied-only Fritz compile and zero-event loader; separate17-event admission required.'}

def _staged(plan,out):
    prefix=Path(plan['prefix']); seen=[]
    for f in plan['source_inventory']['files']:
        p=prefix/f['relative']
        if f['size']==0 and f['relative']=='NEWS':
            if p.exists() or p.is_symlink():raise ValueError('omitted empty NEWS must remain absent from operational prefix')
            continue
        if (any(q.is_symlink() for q in p.parents if q.is_relative_to(prefix))
                or p.is_symlink()
                or not p.resolve().is_relative_to(prefix)
                or digest(p)!=f['sha256'] or (p.stat().st_mode&0o777)!=f['mode']):
            raise ValueError('staged source/card changed')
        seen.append(str(p.absolute()))
    allowed=set(seen)|{str((Path(out)/plan['binary']).absolute())}
    if {str(x.absolute()) for x in prefix.rglob('*') if x.is_file()}-allowed:
        raise ValueError('unbound source-prefix member')
    return seen

def _loader_text(plan):
    return '[global]\nnevents = 0\nrandomseed = 83091\nmain_dir = '+plan['prefix']+'\n'

def run(task,base,out,*,worker_started=None):
    out=Path(out).resolve()
    for rd in out.parents:
        if (rd/science.PLAN).is_file():
            selected=science.verify_worker(rd);spec=science.execution_spec(rd)
            if spec['mode']!='analyze' or spec['task']!=task or out!=rd/selected['output_directory']:
                raise ValueError('build differs from actual ordinary worker')
            break
    else:raise ValueError('ordinary approved build worker required')
    started=time.monotonic() if worker_started is None else worker_started
    plan=build_plan(task,base,out)
    if selected['max_seconds']<RECIPE['max_seconds']:raise ValueError('ordinary ceiling is too small')
    out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):raise ValueError('preserve previous attempt contents; fresh build attempt required')
    prefix=Path(plan['prefix'])
    prefix.mkdir(exist_ok=False)
    for f in plan['source_inventory']['files']:
        if f['size']==0 and f['relative']=='NEWS':continue
        p=prefix/f['relative'];p.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(Path(plan['source_inventory']['original_root'])/f['relative'],p);p.chmod(f['mode'])
    (prefix/'tools/fritz/bin').mkdir(parents=True,exist_ok=True)
    _staged(plan,out)
    atomic_json(out/'build-plan.json',plan)
    (out/'zero-event-loader.ini').write_text(_loader_text(plan))
    from ravel.physics.reinterpret_db import execute_native
    buildout=out/'compile';buildout.mkdir();probeout=out/'loader';probeout.mkdir()
    remaining=RECIPE['max_seconds']-(time.monotonic()-started)-RECIPE['probe_seconds']
    if remaining<=0:raise ValueError('admission/copy exhausted build/check reservation')
    build=execute_native(plan['command'],buildout,{'max_seconds':min(RECIPE['build_seconds'],remaining),'max_ram_mib':RECIPE['max_ram_mib']})
    binary=out/plan['binary']
    if binary.is_symlink() or not binary.is_file() or binary.stat().st_size==0 or not os.access(binary,os.X_OK):raise ValueError('ordinary compiled executable Fritz output required')
    _staged(plan,out)
    if build_plan(task,base,out)!=plan:raise ValueError('source/runtime changed before loader')
    remaining=RECIPE['max_seconds']-(time.monotonic()-started)
    if remaining<=0:raise ValueError('build exhausted loader reservation')
    probe=execute_native(plan['probe_command'],probeout,{'max_seconds':min(RECIPE['probe_seconds'],remaining),'max_ram_mib':RECIPE['max_ram_mib']})
    text=(probeout/'native-stdout.log').read_text()
    if any(x not in text for x in ('Successfully initialized and linked all handlers','Finalising after 0 events','Done')):
        raise ValueError('complete zero-event loader stdout required')
    _staged(plan,out)
    if build_plan(task,base,out)!=plan:raise ValueError('source/runtime changed during build/loader')
    if sum(p.stat().st_size for p in out.rglob('*') if p.is_file())>RECIPE['max_output_bytes']:
        raise ValueError('declared build output ceiling exceeded; retain failure')
    receipt={'schema_version':5,'kind':'checkmate-supplied-fritz-build-receipt','status':'passed',
             'plan_sha256':digest(out/'build-plan.json'),'binary':file_fact(binary),
             'binary_identity':rb.executable_identity(binary),
             'loader_configuration':file_fact(out/'zero-event-loader.ini'),
             'compile':build,'loader':probe,'native_events_processed':0,
             'generation_supported':False,'shower_supported':False,'physics_validated':False,
             'observations':[file_fact(p) for d in (buildout,probeout) for p in sorted(d.iterdir()) if p.is_file()],
             'scope':plan['scope']}
    atomic_json(out/'build-receipt.json',receipt)
    return receipt

def verify_receipt(receipt,plan,base,out):
    out=Path(out).resolve()
    if (receipt!=read_json(out/'build-receipt.json') or plan!=read_json(out/'build-plan.json')
            or plan!=build_plan(plan['task'],base,out) or receipt['plan_sha256']!=digest(out/'build-plan.json')
            or receipt['binary']!=file_fact(out/plan['binary']) or receipt['status']!='passed'
            or receipt['binary_identity']!=rb.executable_identity(out/plan['binary'])
            or receipt['loader_configuration']!=file_fact(out/'zero-event-loader.ini')
            or (out/'zero-event-loader.ini').read_text()!=_loader_text(plan)
            or receipt['generation_supported'] is not False or receipt['shower_supported'] is not False
            or receipt['physics_validated'] is not False or receipt['native_events_processed']!=0):
        raise ValueError('current exact supplied-only build receipt required')
    _staged(plan,out)
    for row in receipt['observations']:bound(row)
    for directory,key,command in [('compile','compile',plan['command']),('loader','loader',plan['probe_command'])]:
        actual=read_json(out/directory/'native-execution.json')
        if actual!=receipt[key] or actual['command']!=command or actual['returncode']!=0 or actual['resource_violation'] is not None:
            raise ValueError('actual successful compile/loader process observation required')
    return receipt
