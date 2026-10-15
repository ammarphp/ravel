#!/usr/bin/env python3
"""Required Linux site-analysis and WMS profiles with prefix-owned records.

The source checkout is derived from this script, never from the caller's cwd.
Mac preparation emits concrete commands for a separately supplied Linux site.
This helper never discovers credentials, downloads data, submits jobs or changes
shell/global configuration. Installation must be explicitly requested.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from ravel.workflow.site_contract import lock_packages, versions_script, sha256
from ravel.workflow.site_doctor import Host, location_check, site_disk_gb
from ravel.setup.steps import subprocess_environment

PROFILES={'site-analysis':('requirements-full.txt','requirements-site.txt'),'site-wms':('requirements-site-wms.lock',)}
LCG_VIEWS=Path('/cvmfs/sft.cern.ch/lcg/views')


def lcg_views(base=LCG_VIEWS,*,machine=None):
    """LCG software views on CVMFS for this CPU, newest release first.

    A view supplies facility software (ROOT, XRootD clients, HTCondor and rucio
    bindings) beside RAVEL's own pinned Python environments; RAVEL's packages
    still come from its requirement files.
    """
    base=Path(base);machine=machine or platform.machine()
    if not base.is_dir():return []
    rows=[]
    for release in base.glob('LCG_*'):
        number=''.join(ch for ch in release.name[4:] if ch.isdigit())
        if not number:continue
        for view in release.glob(machine+'-*-opt'):
            if (view/'setup.sh').is_file():rows.append((int(number),release.name,view.name,view))
    rows.sort(key=lambda r:(r[0],r[1],r[2]),reverse=True)
    return [{'release':r[1],'platform':r[2],'path':str(r[3]),'setup':str(r[3]/'setup.sh')} for r in rows]


def write_lcg_binding(root,view):
    """Record the chosen LCG view and a helper that loads it into one shell."""
    chosen = lcg_choice(view)
    owned=Path(root)/'.ravel-site';owned.mkdir(parents=True, exist_ok=True)
    atomic_json(owned/'lcg-view.json', chosen)
    (owned/'lcg-view.sh').write_text('# owned by the RAVEL installer: source this to use the facility LCG view\n'
                                     + ('source '+shlex.quote(str(Path(chosen['path'])/'setup.sh'))+'\n'
                                        if chosen['path'] else '# This site uses no LCG view.\n'))
    return {**chosen, 'view':chosen['path'],'helper':str(owned/'lcg-view.sh')}


def lcg_choice(view,*,prefix=None):
    if not view or view == 'auto':
        candidates = lcg_views()
        listing = '\n'.join(row['path'] for row in candidates) or '(no candidates for this CPU)'
        target=shlex.quote(str(prefix)) if prefix is not None else '<work-prefix>'
        choice=shlex.quote(candidates[0]['path']) if candidates else 'none'
        raise ValueError('Choose an explicit LCG view; candidates:\n' + listing + '\nRerun: '
                         'bash scripts/setup/install.sh --profile site --prefix '+target+
                         ' --lcg-view '+choice+'; on a site without CVMFS use --lcg-view none')
    if str(view) == 'none':
        return {'schema_version':1, 'choice':'none', 'release':None, 'platform':None, 'path':None}
    view=Path(view)
    if not view.is_absolute() or not (view/'setup.sh').is_file():
        raise ValueError('LCG view requires an absolute path with setup.sh: '+str(view))
    return {'schema_version':1, 'choice':str(view), 'release':view.parent.name, 'platform':view.name, 'path':str(view)}


def atomic_json(path, value):
    temporary=path.with_suffix('.tmp')
    with temporary.open('x') as handle:
        json.dump(value,handle,indent=2,sort_keys=True);handle.write('\n');handle.flush();os.fsync(handle.fileno())
    os.replace(temporary,path)


def release_id(root):
    """Use the exact release tag when present, otherwise the installed commit."""
    env = dict(os.environ)
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None);env.pop('PYTHONSTARTUP',None)
    tag = subprocess.run(['/usr/bin/git','describe','--tags','--exact-match','HEAD'],cwd=root,
                         env=env,capture_output=True,text=True,check=False)
    if tag.returncode == 0:return tag.stdout.strip()
    commit = subprocess.run(['/usr/bin/git','rev-parse','HEAD'],cwd=root,
                            env=env,capture_output=True,text=True,check=False)
    if commit.returncode != 0 or not commit.stdout.strip():
        raise ValueError('RAVEL release cannot be identified; install from a git checkout of the release')
    return commit.stdout.strip()


def check_campaign(prefix,release,choice):
    """Check release ownership before either the bootstrap run loop or site pip."""
    owned=Path(prefix)/'.ravel-site'
    if any(part.is_symlink() for part in (owned,*owned.parents)):
        raise ValueError('ordinary owned site directory required')
    campaign=owned/'campaign.json'
    if campaign.is_symlink():raise ValueError('Ordinary prefix-owned campaign record required')
    if campaign.is_file():
        previous=json.loads(campaign.read_text())
        if previous['release']!=release:
            raise ValueError(f"Prefix contains release {previous['release']}; requested release {release}. "
                             'Install the new release into a new prefix once the current campaign ends.')
        if previous['lcg_view']!=choice:raise ValueError('LCG view changed; install into a new prefix once the current campaign ends')
    elif owned.exists() and any(owned.iterdir()):
        raise ValueError('Unrecorded site installation retained; install this release into a new prefix once the current campaign ends')
    return campaign


def pin(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('ordinary setup source required')
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def plan(root=ROOT,*,linux_root=None,prefix=None):
    root=Path(root).absolute()
    if not (root/'src/ravel/__init__.py').is_file():raise ValueError('actual RAVEL checkout required')
    lock_packages(root/'requirements-site-wms.lock')
    required={name:pin(root/name) for name in ('requirements-full.txt','requirements-site.txt','requirements-site-wms.lock','environment/site-profiles.json','pyproject.toml','scripts/setup/site_installation.py')}
    manifest=root/'environment/site-profiles.json'
    raw=manifest.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=required['environment/site-profiles.json']['sha256']:raise ValueError('consumed site manifest differs from original pin')
    metadata=json.loads(raw)
    if metadata['platform']['python']!='3.12' or metadata['platform']['execution_os']!='Linux':raise ValueError('closed required Linux Python3.12 profile differs')
    remote=platform.system()!='Linux';target=Path(linux_root or root).absolute()
    if remote and linux_root is None:raise ValueError('Mac/other preparation requires explicit absolute --linux-root on the supplied remote site')
    if any(p in ('.','..') for p in target.parts):raise ValueError('literal Linux checkout path required')
    # The same checkout commit/required files must be transferred by the user,
    # independently of credentials, before these concrete commands can execute.
    install_prefix=Path(prefix or target).absolute()
    command=['python3.12',str(target/'scripts/setup/site_installation.py'),'--install','--prefix',str(install_prefix),'--lcg-view','none']
    return {'schema_version':1,'kind':'required-site-profile-plan','local_platform':platform.system(),
            'execution_platform':'Linux','remote_site_required':remote,'linux_source_root':str(target),
            'required_profiles':list(PROFILES),'source_pins':list(required.values()),'remote_install_argv':command,
            'local_install_argv':None if remote else command,
            'prefix':str(install_prefix),
            'wms_argv':[str(install_prefix/'bin/ravel-snakemake'),'--snakefile','ABSOLUTE_EXPORTED_SNAKEFILE','--directory','ABSOLUTE_EXPORT_DIRECTORY','--cores','1','--retries','0'],
            'analysis_python':str(install_prefix/'.ravel-site/site-analysis/bin/python'),
            'requirements_required':True,'runtime_or_site_data_qualified':False,
            'lcg_views':lcg_views()[:3],
            'prerequisites':['Linux Python3.12 and source-build prerequisites from the native setup guide before full host installation.',
                'Exact source checkout at linux_source_root, site credential policy and permitted RSE access supplied separately.',
                'Separate WMS environment prevents packaging<26 from replacing proven full host packaging26.3.']}


def check_interpreter(python, target, env=None):
    python=Path(python);target=Path(target)
    if any(p.is_symlink() for p in (python,*python.parents)) or not python.is_file():raise ValueError('ordinary copied site interpreter required')
    check='import sys,json,platform;print(json.dumps([sys.prefix,sys.base_prefix,list(sys.version_info[:2]),platform.system(),platform.python_implementation()]))'
    observed=subprocess.run([str(python),'-I','-B','-c',check],env=env,check=True,capture_output=True,text=True)
    prefix,base_prefix,version,system,implementation=json.loads(observed.stdout)
    if Path(prefix).resolve()!=target.resolve() or Path(base_prefix).resolve()==target.resolve() or version!=[3,12] or system!='Linux' or implementation!='CPython':raise ValueError('site interpreter must belong to its declared Linux CPython3.12 environment')


def install(root=ROOT,*,prefix=None,lcg_view=None,host=None):
    root=Path(root).absolute()
    if platform.system()!='Linux' or sys.version_info[:2]!=(3,12):raise ValueError('actual installation requires Linux CPython3.12; use --plan --linux-root on other platforms')
    prefix=Path(prefix or root).absolute()
    owned=prefix/'.ravel-site'
    if any(p.is_symlink() for p in (owned,*owned.parents)):raise ValueError('ordinary owned site directory required')
    choice=lcg_choice(lcg_view if lcg_view is not None else os.environ.get('RAVEL_LCG_VIEW'),prefix=prefix)
    location=location_check('prefix',prefix,host=host or Host(),threshold_gb=site_disk_gb())
    if location['status']=='fail':raise ValueError(location['detail']+'; '+location['fix'])
    release=release_id(root)
    campaign=check_campaign(prefix,release,choice)
    value=plan(root,prefix=prefix);before={p['path']:p for p in value['source_pins']}
    packages=lock_packages(root/'requirements-site-wms.lock')
    owned.mkdir(parents=True,exist_ok=True)
    if not campaign.exists():atomic_json(campaign,{'schema_version':1,'release':release,'lcg_view':choice})
    env=subprocess_environment(prefix,{'JOBS':'1','PLATFORM':'linux'})
    env['PYTHONNOUSERSITE']='1'
    for key in ('APPTAINER_CACHEDIR','APPTAINER_TMPDIR','TMPDIR','PIP_CACHE_DIR','XDG_CACHE_HOME'):
        Path(env[key]).mkdir(parents=True,exist_ok=True)
    for name,requirements in PROFILES.items():
        path=owned/name;marker=path/'ravel-site-profile.json'
        expected={'schema_version':1,'profile':name,'source_root':str(root),'requirements':[before[str(root/x)] for x in requirements],'setup_source_pins':list(before.values())}
        if path.exists():
            if path.is_symlink() or not marker.is_file() or json.loads(marker.read_text())!=expected:
                raise ValueError(f'Existing environment declaration differs within release {release}; '
                                 'install the reviewed release into a new prefix once the current campaign ends')
            if not (path/'bin/python').is_file():raise ValueError('existing profile is incomplete; retain it for explicit recovery')
        else:
            subprocess.run([sys.executable,'-B','-m','venv','--copies',str(path)],env=env,cwd=root,check=True)
            # Mark immediately so an interrupted install can resume its own exact
            # source profile. This marker is not an installed/readiness receipt.
            with marker.open('x') as f:json.dump(expected,f,sort_keys=True);f.write('\n')
        python=path/'bin/python';argv=[str(python),'-B','-m','pip','install']
        if name=='site-wms':argv.append('--require-hashes')
        for logical_requirement in requirements:argv.extend(['-r',str(root/logical_requirement)])
        # requirements-full already includes the current local project exactly
        # once. WMS intentionally installs no RAVEL or host dependencies.
        check_interpreter(python,path,env)
        subprocess.run(argv,cwd=root,env=env,check=True)
        check_interpreter(python,path,env)
        subprocess.run([str(python),'-B','-m','pip','check'],cwd=root,env=env,check=True)
        if before!={p:pin(p) for p in before}:raise ValueError('setup source changed during installation')
        check_interpreter(python,path,env)
        freeze=subprocess.run([str(python),'-B','-m','pip','freeze','--all'],cwd=root,env=env,check=True,capture_output=True,text=True)
        destination=path/'ravel-site-installed.json'
        raw=(json.dumps({'profile':name,'source_pins':list(before.values()),'pip_check':True,'freeze':freeze.stdout,
                        'scientific_or_site_access_qualified':False},sort_keys=True,indent=2)+'\n').encode()
        temporary=path/'ravel-site-installed.tmp'
        with temporary.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temporary,destination)
    python=owned/'site-wms/bin/python'
    observed=subprocess.run([str(python),'-I','-B','-c',versions_script(packages)],cwd=root,env=env,
                            check=True,capture_output=True,text=True)
    installed=json.loads(observed.stdout)
    if installed!=packages:raise ValueError('Installed WMS package versions differ from the hash lock')
    snake=owned/'site-wms/bin/snakemake'
    version=subprocess.run([str(snake),'--version'],cwd=root,env=env,check=True,capture_output=True,text=True)
    if version.stdout.strip()!=packages['snakemake']:raise ValueError('Snakemake executable version differs from the hash lock')
    shim=prefix/'bin/ravel-snakemake';shim.parent.mkdir(parents=True,exist_ok=True)
    content=('#!/bin/sh\n# owned by the RAVEL installer\nunset PYTHONPATH PYTHONHOME PYTHONSTARTUP\n'
             'export PYTHONNOUSERSITE=1\nexec '+shlex.quote(str(owned/'site-wms/bin/snakemake'))+' "$@"\n')
    if shim.is_symlink() or shim.exists() and shim.read_text()!=content:raise ValueError('Existing unrelated ravel-snakemake retained; choose a new prefix')
    shim.write_text(content);shim.chmod(0o755)
    lock=owned/'requirements-site-wms.lock'
    if lock.is_symlink():raise ValueError('Ordinary prefix-owned WMS lock required')
    lock.write_bytes((root/'requirements-site-wms.lock').read_bytes())
    record={'schema_version':1,'snakemake':str(owned/'site-wms/bin/snakemake'),'shim':str(shim),
            'version':packages['snakemake'],'plugins':{k:v for k,v in packages.items() if k.startswith('snakemake-executor-plugin-')},
            'packages':packages,'lock':str(lock),'lock_sha256':sha256(lock),'release':release,
            'analysis_python':str(owned/'site-analysis/bin/python')}
    atomic_json(owned/'wms.json',record)
    binding=write_lcg_binding(prefix,choice['choice'])
    return {'installed_profiles':list(PROFILES),'prefix':str(prefix),'source_pins':list(before.values()),
            'wms':record,'lcg_view':binding,'scientific_or_site_access_qualified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--plan',action='store_true');mode.add_argument('--install',action='store_true')
    parser.add_argument('--linux-root',type=Path);parser.add_argument('--out',type=Path)
    parser.add_argument('--prefix',type=Path,help='work-area prefix for both environments, records and caches')
    parser.add_argument('--lcg-view',help="with --install: explicit view path or 'none'; auto lists candidates and refuses")
    args=parser.parse_args(argv)
    if args.install and (args.linux_root is not None or args.out is not None):parser.error('--install uses this exact Linux checkout; no remote/local substitution')
    if args.lcg_view and not args.install:parser.error('--lcg-view applies to --install')
    try:
        value=install(prefix=args.prefix,lcg_view=args.lcg_view) if args.install else plan(linux_root=args.linux_root,prefix=args.prefix)
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print('site install: '+str(error),file=sys.stderr);return 2
    raw=json.dumps(value,indent=2,sort_keys=True)+'\n'
    if args.out is not None:
        if any(p.is_symlink() for p in (args.out,*args.out.parents)):raise ValueError('ordinary fresh manifest path required')
        with args.out.open('x') as f:f.write(raw)
    else:print(raw,end='')
    return 0


if __name__=='__main__':raise SystemExit(main())
