#!/usr/bin/env python3
"""Required Linux site-analysis and WMS profiles; --plan is stdlib-only.

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
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PROFILES={'site-analysis':('requirements-full.txt','requirements-site.txt'),'site-wms':('requirements-site-wms.txt',)}
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
    view=Path(view)
    if not (view/'setup.sh').is_file():raise ValueError('LCG view without setup.sh: '+str(view))
    owned=Path(root)/'.ravel-site';owned.mkdir(exist_ok=True)
    (owned/'lcg-view.json').write_text(json.dumps({'view':str(view),'setup':str(view/'setup.sh')},indent=2)+'\n')
    (owned/'lcg-view.sh').write_text('# owned by the RAVEL installer: source this to use the facility LCG view\n'
                                     'source '+str(view/'setup.sh')+'\n')
    return {'view':str(view),'helper':str(owned/'lcg-view.sh')}


def pin(path):
    path=Path(path)
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('ordinary setup source required')
    raw=path.read_bytes();return {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}


def plan(root=ROOT,*,linux_root=None):
    root=Path(root).absolute()
    if not (root/'src/ravel/__init__.py').is_file():raise ValueError('actual RAVEL checkout required')
    required={name:pin(root/name) for name in ('requirements-full.txt','requirements-site.txt','requirements-site-wms.txt','environment/site-profiles.json','pyproject.toml','scripts/setup/site_installation.py')}
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
    command=['python3.12',str(target/'scripts/setup/site_installation.py'),'--install']
    return {'schema_version':1,'kind':'required-site-profile-plan','local_platform':platform.system(),
            'execution_platform':'Linux','remote_site_required':remote,'linux_source_root':str(target),
            'required_profiles':list(PROFILES),'source_pins':list(required.values()),'remote_install_argv':command,
            'local_install_argv':None if remote else command,
            'wms_argv':[str(target/'.ravel-site/site-wms/bin/snakemake'),'--snakefile','ABSOLUTE_EXPORTED_SNAKEFILE','--directory','ABSOLUTE_EXPORT_DIRECTORY','--cores','1','--retries','0'],
            'analysis_python':str(target/'.ravel-site/site-analysis/bin/python'),
            'requirements_required':True,'runtime_or_site_data_qualified':False,
            'lcg_views':lcg_views()[:3],
            'prerequisites':['Linux Python3.12 and source-build prerequisites from the native setup guide before full host installation.',
                'Exact source checkout at linux_source_root, site credential policy and permitted RSE access supplied separately.',
                'Separate WMS environment prevents packaging<26 from replacing proven full host packaging26.3.']}


def check_interpreter(python, target):
    python=Path(python);target=Path(target)
    if any(p.is_symlink() for p in (python,*python.parents)) or not python.is_file():raise ValueError('ordinary copied site interpreter required')
    check='import sys,json,platform;print(json.dumps([sys.prefix,sys.base_prefix,list(sys.version_info[:2]),platform.system(),platform.python_implementation()]))'
    observed=subprocess.run([str(python),'-I','-c',check],check=True,capture_output=True,text=True)
    prefix,base_prefix,version,system,implementation=json.loads(observed.stdout)
    if Path(prefix).resolve()!=target.resolve() or Path(base_prefix).resolve()==target.resolve() or version!=[3,12] or system!='Linux' or implementation!='CPython':raise ValueError('site interpreter must belong to its declared Linux CPython3.12 environment')


def install(root=ROOT):
    root=Path(root).absolute()
    if platform.system()!='Linux' or sys.version_info[:2]!=(3,12):raise ValueError('actual installation requires Linux CPython3.12; use --plan --linux-root on other platforms')
    value=plan(root);before={p['path']:p for p in value['source_pins']}
    owned=root/'.ravel-site'
    if any(p.is_symlink() for p in (owned,*owned.parents)):raise ValueError('ordinary owned site directory required')
    owned.mkdir(exist_ok=True)
    for name,requirements in PROFILES.items():
        path=owned/name;marker=path/'ravel-site-profile.json'
        expected={'schema_version':1,'profile':name,'source_root':str(root),'requirements':[before[str(root/x)] for x in requirements],'setup_source_pins':list(before.values())}
        if path.exists():
            if path.is_symlink() or not marker.is_file() or json.loads(marker.read_text())!=expected:raise ValueError('existing unrelated or differently declared environment retained; choose a fresh checkout/profile')
            if not (path/'bin/python').is_file():raise ValueError('existing profile is incomplete; retain it for explicit recovery')
        else:
            subprocess.run([sys.executable,'-B','-m','venv','--copies',str(path)],cwd=root,check=True)
            # Mark immediately so an interrupted install can resume its own exact
            # source profile. This marker is not an installed/readiness receipt.
            with marker.open('x') as f:json.dump(expected,f,sort_keys=True);f.write('\n')
        python=path/'bin/python';argv=[str(python),'-B','-m','pip','install']
        for logical_requirement in requirements:argv.extend(['-r',str(root/logical_requirement)])
        # requirements-full already includes the current local project exactly
        # once. WMS intentionally installs no RAVEL or host dependencies.
        check_interpreter(python,path)
        subprocess.run(argv,cwd=root,check=True)
        check_interpreter(python,path)
        subprocess.run([str(python),'-B','-m','pip','check'],cwd=root,check=True)
        if before!={p:pin(p) for p in before}:raise ValueError('setup source changed during installation')
        check_interpreter(python,path)
        freeze=subprocess.run([str(python),'-B','-m','pip','freeze','--all'],cwd=root,check=True,capture_output=True,text=True)
        destination=path/'ravel-site-installed.json'
        raw=(json.dumps({'profile':name,'source_pins':list(before.values()),'pip_check':True,'freeze':freeze.stdout,
                        'scientific_or_site_access_qualified':False},sort_keys=True,indent=2)+'\n').encode()
        temporary=path/'ravel-site-installed.tmp'
        with temporary.open('xb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(temporary,destination)
    return {'installed_profiles':list(PROFILES),'source_pins':list(before.values()),'scientific_or_site_access_qualified':False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--plan',action='store_true');mode.add_argument('--install',action='store_true')
    parser.add_argument('--linux-root',type=Path);parser.add_argument('--out',type=Path)
    parser.add_argument('--lcg-view',help="with --install: an LCG view directory on CVMFS, or 'auto' for the newest one")
    args=parser.parse_args(argv)
    if args.install and (args.linux_root is not None or args.out is not None):parser.error('--install uses this exact Linux checkout; no remote/local substitution')
    if args.lcg_view and not args.install:parser.error('--lcg-view applies to --install')
    value=install() if args.install else plan(linux_root=args.linux_root)
    if args.lcg_view:
        views=lcg_views()
        chosen=(views[0]['path'] if views else None) if args.lcg_view=='auto' else args.lcg_view
        value['lcg_view']=write_lcg_binding(ROOT,chosen) if chosen else None
    raw=json.dumps(value,indent=2,sort_keys=True)+'\n'
    if args.out is not None:
        if any(p.is_symlink() for p in (args.out,*args.out.parents)):raise ValueError('ordinary fresh manifest path required')
        with args.out.open('x') as f:f.write(raw)
    else:print(raw,end='')
    return 0


if __name__=='__main__':raise SystemExit(main())
