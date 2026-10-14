"""Closed offline FastJet3.4.0/fjcontrib1.048 library recipe for MA5's source runtime.

Planning is read-only. Ordinary science_worker/supervisor owns execution, group
cleanup and fresh authority. This dependency build is not a collider endpoint.
"""
from pathlib import Path
import base64,hashlib,json,os,shutil,stat,tarfile,time
from ravel.workflow.science import regular
from ravel.workflow.state_io import atomic_json,read_json
from ravel.workflow import execution

ARCHIVES={'fastjet-3.4.0':'ee07c8747c8ead86d88de4a9e4e8d1e9e7d7614973f5631ba8297f7a02478b91',
          'fjcontrib-1.048':'f9989d3b6aeb22848bcf91095c30607f027d3ef277a4f0f704a8f0fc2e766981'}
TOOLS={'shell','make','c','cxx','fortran','ar','ranlib','strip'}
ENVIRONMENT={'PATH','SDKROOT','LIBRARY_PATH','LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','CPPFLAGS','CFLAGS','CXXFLAGS','FCFLAGS'}
PRODUCTS=['bin/fastjet-config','include/fastjet/PseudoJet.hh','lib/libfastjet.a',
          'include/fastjet/contrib/Nsubjettiness.hh','lib/libNsubjettiness.a']
RECIPE={'name':'fastjet3.4.0-fjcontrib1.048-allplugins','workers':1,'max_seconds':1800,'command_max_seconds':600}

def pin(value,base):
 if type(value) is not dict or set(value)!={'path','sha256'}:raise ValueError('exact ordinary pin required')
 path=regular(value['path'],base)
 if hashlib.sha256(path.read_bytes()).hexdigest()!=value['sha256']:raise ValueError('bound bytes changed')
 return path

def source_inventory(value,base):
 path=pin(value,base);inventory=read_json(path)
 if (type(inventory) is not dict or set(inventory)!={'schema_version','archives','source_execution','source_import','native_build'}
     or type(inventory['schema_version']) is not int or inventory['schema_version']!=1
     or type(inventory['archives']) is not list or len(inventory['archives'])!=2
     or any(inventory[k] is not False for k in ('source_execution','source_import','native_build'))):raise ValueError('exact two-archive source inventory required')
 files=[path];seen=set()
 for package in inventory['archives']:
  if type(package) is not dict or set(package)!={'archive','source_root','full_members','ordinary_source_files','uncompressed_file_bytes','inventory'}:raise ValueError('closed archive population required')
  root=Path(package['source_root']);name=root.name
  if not root.is_absolute() or name not in ARCHIVES or name in seen:raise ValueError('exact distinct upstream source roots required')
  seen.add(name)
  if any(p.is_symlink() for p in [root,*root.parents,*root.rglob('*')]):raise ValueError('ordinary source tree required')
  archive=pin({k:package['archive'][k] for k in ('path','sha256')},base)
  if package['archive']['sha256']!=ARCHIVES[name]:raise ValueError('exact released archive required')
  declared={row['archive_member']:row for row in package['inventory']}
  if len(declared)!=len(package['inventory']):raise ValueError('duplicate source row')
  total=0
  with tarfile.open(archive,'r:gz') as stream:
   members=stream.getmembers()
   ordinary=[m for m in members if m.isfile()]
   if (len(members)!=package['full_members'] or len(ordinary)!=package['ordinary_source_files']
       or len(ordinary)!=len(declared) or any(not(m.isdir() or m.isfile()) for m in members)):raise ValueError('complete ordinary archive census required')
   for member in ordinary:
    relative=Path(member.name)
    if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!=name:raise ValueError('unsafe archive member')
    row=declared.get(member.name)
    if row is None or set(row)!={'path','archive_member','sha256','bytes','mode'}:raise ValueError('full member missing or malformed')
    source=regular(row['path'],base)
    if source!=root.joinpath(*relative.parts[1:]).resolve():raise ValueError('source member path differs')
    if member.size>32_000_000:raise ValueError('source member exceeds bounded population')
    raw=stream.extractfile(member).read()
    if (hashlib.sha256(raw).hexdigest()!=row['sha256'] or raw!=source.read_bytes()
        or len(raw)!=row['bytes'] or stat.S_IMODE(source.stat().st_mode)!=(row['mode']&0o777)
        or row['mode']!=(member.mode&0o777)):raise ValueError('source bytes/modes differ from exact archive')
    total+=len(raw);files.append(source)
  if total!=package['uncompressed_file_bytes'] or total>32_000_000:raise ValueError('bounded full source bytes differ')
  if {p.resolve() for p in root.rglob('*') if p.is_file()}!={Path(r['path']).resolve() for r in declared.values()}:raise ValueError('source tree added or omitted members')
  files.append(archive)
 if seen!=set(ARCHIVES):raise ValueError('full two-distribution population required')
 return inventory,list(dict.fromkeys(files))

def configuration(task,base):
 from ravel.physics import routine_build
 routine_build.validate(task);path=regular(task['input'],base);config=read_json(path)
 if (type(config) is not dict or set(config)!={'schema_version','kind','source_inventory','recipe','runtime'}
     or type(config['schema_version']) is not int or config['schema_version']!=4
     or config['kind']!='autotools-fastjet-bundle' or config['recipe']!=RECIPE
     or any(type(config['recipe'].get(k)) is not int for k in ('workers','max_seconds','command_max_seconds'))):raise ValueError('closed full upstream autotools bundle required')
 runtime=config['runtime']
 if (type(runtime) is not dict or set(runtime)!={'tools','artifacts','environment','execution_identity'}
     or type(runtime['tools']) is not dict or set(runtime['tools'])!=TOOLS
     or type(runtime['artifacts']) is not list or type(runtime['environment']) is not dict
     or not set(runtime['environment'])<=ENVIRONMENT
     or any(type(v) is not str or '\0' in v for v in runtime['environment'].values())):raise ValueError('closed source-bound runtime required')
 identities={k:routine_build.executable_identity(v['path']) for k,v in runtime['tools'].items()}
 for name,fact in runtime['tools'].items():
  if set(fact)!={'path','sha256'} or fact['sha256']!=identities[name]['sha256']:raise ValueError('runtime executable target differs')
 if identities!=runtime['execution_identity']:raise ValueError('executable aliases changed')
 artifacts=[pin(p,base) for p in runtime['artifacts']]
 inventory,files=source_inventory(config['source_inventory'],base)
 files += [path,*artifacts,*[Path(v['resolved_path']) for v in identities.values()]]
 return config,inventory,list(dict.fromkeys(files))

def inputs(task,base):return configuration(task,base)[2]
def execution_seconds(task,base):return configuration(task,base)[0]['recipe']['max_seconds']

def build_plan(task,base,out):
 config,inventory,files=configuration(task,base);out=Path(out).absolute()
 if any(p.is_symlink() for p in (out,*out.parents)):raise ValueError('ordinary approved output root required')
 if out.name!='attempt-1' or out.parent.name!='outputs':raise ValueError('prospective scientific attempt-1 output required')
 prefix=out/'prefix';work=out.parent.parent/'work/fastjet-build-attempt-1/source'
 tools=config['runtime']['tools'];shell=tools['shell']['path'];make=tools['make']['path']
 commands=[{'argv':[shell,str(work/'fastjet-3.4.0/configure'),'--prefix='+str(prefix),'--enable-allplugins'],'cwd':str(work/'fastjet-3.4.0')},
           {'argv':[make,'-j1'],'cwd':str(work/'fastjet-3.4.0')},
           {'argv':[make,'install'],'cwd':str(work/'fastjet-3.4.0')},
           {'argv':[shell,str(work/'fjcontrib-1.048/configure'),'--fastjet-config='+str(prefix/'bin/fastjet-config'),'CXXFLAGS=-fPIC'],'cwd':str(work/'fjcontrib-1.048')},
           {'argv':[make,'-j1'],'cwd':str(work/'fjcontrib-1.048')},
           {'argv':[make,'install'],'cwd':str(work/'fjcontrib-1.048')}]
 return {'schema_version':4,'kind':'routine-build-plan','framework':'autotools-library','recipe':RECIPE,
         'commands':commands,'output_directory':str(out),'work_directory':str(work),'prefix':str(prefix),'source_inventory':inventory,
         'runtime':config['runtime'],'inputs':[str(p) for p in files],
         'task':dict(task),'input_snapshot':execution.snapshot(Path(base),[str(p) for p in files]),
         'products':['prefix/'+p for p in PRODUCTS],'physics_validated':False,'qualified_native_runtime':False}

def normalize_owned_links(out):
 """Retain internal native alias evidence before ordinary byte materialization.

 All aliases must resolve to job-owned ordinary files before any alias changes.
 No outside/directory/dangling/cyclic native link is admitted or moved.
 """
 out=Path(out).resolve();rows=[]
 for path in sorted(out.rglob('*')):
  if not path.is_symlink():continue
  target=path.resolve(strict=True)
  if not target.is_relative_to(out) or not target.is_file():raise ValueError('native alias escapes or is not an ordinary file')
  raw=target.read_bytes()
  rows.append({'path':str(path.relative_to(out)),'original_target':os.readlink(path),'resolved_relative_target':str(target.relative_to(out)),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw),'mode':stat.S_IMODE(target.stat().st_mode)})
 atomic_json(out/'owned-native-aliases.json',{'schema_version':1,'aliases':rows,'meaning':'Original job-owned native aliases retained before byte-equivalent ordinary artifact materialization'})
 for row in rows:
  path=out/row['path'];target=out/row['resolved_relative_target']
  raw=target.read_bytes()
  if not path.is_symlink() or os.readlink(path)!=row['original_target'] or hashlib.sha256(raw).hexdigest()!=row['sha256']:raise ValueError('native alias changed before materialization')
  path.unlink();path.write_bytes(raw);path.chmod(row['mode'])
 return rows

def environment(plan,out):
 from ravel.physics import routine_build
 out=Path(out)
 workspace=Path(plan['work_directory']).parent
 env=routine_build.isolated_process_environment(workspace/'home',workspace/'tmp')
 env.update(plan['runtime']['environment'])
 for key,name in [('CC','c'),('CXX','cxx'),('F77','fortran'),('FC','fortran'),('AR','ar'),('RANLIB','ranlib'),('STRIP','strip')]:env[key]=plan['runtime']['tools'][name]['path']
 return env


def run(task,base,out,*,worker_started=None):
 from ravel.physics import routine_build
 started=time.monotonic() if worker_started is None else worker_started
 deadline=started+RECIPE['max_seconds'];plan=build_plan(task,base,out);out=Path(out)
 if not out.is_dir() or any(out.iterdir()):raise ValueError('fresh worker-owned attempt root required')
 before={p:execution.file_hash(Path(p)) for p in plan['inputs']}
 work=Path(plan['work_directory'])
 if work.parent.exists() or any(p.is_symlink() for p in (work,*work.parents)):raise ValueError('fresh owned native work required')
 work.mkdir(parents=True)
 for package in plan['source_inventory']['archives']:
  root=Path(package['source_root']);target=work/root.name;target.mkdir()
  for row in package['inventory']:
   source=Path(row['path']);destination=target/source.relative_to(root)
   destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
 for folder in ('home','tmp'):(work.parent/folder).mkdir()
 env=environment(plan,out)
 observations=[]
 for index,command in enumerate(plan['commands']):
  # Recheck invocation aliases before every native operation, and retain exact
  # failed observations through the same existing transport helper.
  configuration(task,base)
  log=out/('command-'+str(index+1)+'.json')
  routine_build._process(command['argv'],command['cwd'],env,log,work_deadline=deadline,max_seconds=RECIPE['command_max_seconds'])
  observations.append({'path':log.name,'sha256':execution.file_hash(log)})
 configuration(task,base)
 if {p:execution.file_hash(Path(p)) for p in plan['inputs']}!=before:raise ValueError('source/runtime changed during build')
 staged=[]
 for package in plan['source_inventory']['archives']:
  root=Path(package['source_root'])
  for row in package['inventory']:
   relative=Path(row['path']).relative_to(root);copy=work/root.name/relative
   if execution.file_hash(copy)!=row['sha256']:raise ValueError('native build changed original compilation source')
   staged.append({'path':str(copy),'sha256':row['sha256'],'mode':row['mode']})
 atomic_json(out/'staged-source-observation.json',{'ordinary_original_members_unchanged':staged,'native_generated_work_directory':str(work),'scope':'Full original members retained; generated build files are work products, not substituted source'})
 aliases=normalize_owned_links(out)
 artifacts=[]
 for relative in plan['products']:
  path=regular(relative,out)
  if path.stat().st_size==0:raise ValueError('native required product is empty')
  artifacts.append({'path':relative,'sha256':execution.file_hash(path),'size':path.stat().st_size})
 receipt={'schema_version':4,'kind':'autotools-library-build-receipt','status':'passed','physics_validated':False,
          'build_plan_sha256':execution.digest(plan),'products':artifacts,'observations':observations,
          'materialized_owned_aliases':aliases,'source_runtime_unchanged':True,
          'scope':'Observed full offline two-library source build; no MA5 events or analysis acceptance'}
 atomic_json(out/'build-plan.json',plan);atomic_json(out/'build-receipt.json',receipt)
 verify_receipt(receipt,plan,base,out)
 return {'status':'passed','physics_validated':False,'kind':'autotools-library-build','receipt':receipt,
         'limitations':['Toolchain executable/artifact bytes are bound; transitive OS/compiler/SDK closure is not inferred.',
                        'Full MA5 OSU truth/detector analysis and scientific comparison remain unexecuted.',
                        'Owned internal alias byte materialization is recorded; original install inode identity is not claimed.']}

def verify_receipt(receipt,plan,base,outroot):
 out=Path(outroot).resolve()
 if build_plan(plan['task'],base,out)!=plan:raise ValueError('prospective source/runtime/build plan changed')
 if (type(receipt) is not dict or set(receipt)!={'schema_version','kind','status','physics_validated','build_plan_sha256','products','observations','materialized_owned_aliases','source_runtime_unchanged','scope'}
     or receipt['schema_version']!=4 or receipt['kind']!='autotools-library-build-receipt'
     or receipt['status']!='passed' or receipt['physics_validated'] is not False
     or receipt['source_runtime_unchanged'] is not True or receipt['build_plan_sha256']!=execution.digest(plan)
     or len(receipt['observations'])!=6 or [p['path'] for p in receipt['products']]!=plan['products']):raise ValueError('complete exact library-build receipt required')
 for index,row in enumerate(receipt['observations']):
  if set(row)!={'path','sha256'} or row['path']!='command-'+str(index+1)+'.json':raise ValueError('native command observation mismatch')
  record=read_json(pin(row,out));command=plan['commands'][index]
  if (set(record)!={'schema_version','command','returncode','cwd','environment','started_at','finished_at','stdout_base64','stderr_base64'}
      or record['schema_version']!=2 or record['command']!=command['argv'] or record['cwd']!=command['cwd']
      or record['environment']!=environment(plan,out) or type(record['returncode']) is not int or record['returncode']!=0):raise ValueError('failed or foreign native command')
  base64.b64decode(record['stdout_base64'],validate=True);base64.b64decode(record['stderr_base64'],validate=True)
 for row in receipt['products']:
  p=pin({k:row[k] for k in ('path','sha256')},out)
  if p.stat().st_size!=row['size'] or row['size']<=0:raise ValueError('required artifact population differs')
 staged=[];work=Path(plan['work_directory'])
 for package in plan['source_inventory']['archives']:
  root=Path(package['source_root'])
  for row in package['inventory']:
   copy=work/root.name/Path(row['path']).relative_to(root)
   if execution.file_hash(regular(str(copy),base))!=row['sha256'] or stat.S_IMODE(copy.stat().st_mode)!=(row['mode']&0o777):raise ValueError('retained original compilation source changed')
   staged.append({'path':str(copy),'sha256':row['sha256'],'mode':row['mode']})
 if read_json(out/'staged-source-observation.json')['ordinary_original_members_unchanged']!=staged:raise ValueError('retained staged source observation differs')
 if any(p.is_symlink() for p in out.rglob('*')):raise ValueError('untracked native output alias')
 if read_json(out/'owned-native-aliases.json')['aliases']!=receipt['materialized_owned_aliases']:raise ValueError('native alias observations differ')
 for row in receipt['materialized_owned_aliases']:
  p=regular(row['path'],out)
  if execution.file_hash(p)!=row['sha256'] or p.stat().st_size!=row['size']:raise ValueError('owned alias byte materialization changed')
 return {'status':'passed','physics_validated':False,'scope':'Retained six-command/source/product receipt integrity; actual process authenticity and scientific efficacy separate'}
