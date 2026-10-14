"""Fake external clients for execution-backend tests.

Each fake is a small Python program behind a shell wrapper placed first on PATH.
State lives in a JSON file named by FAKE_STATE so tests can inspect and steer it.
No container, VM, scheduler or network is touched.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def install(bin_dir, name, source, state):
    """Write <bin_dir>/<name> as a shell wrapper around a Python fake."""
    bin_dir = Path(bin_dir)
    bin_dir.mkdir(parents=True, exist_ok=True)
    program = bin_dir / f"_{name}_fake.py"
    program.write_text(source)
    wrapper = bin_dir / name
    wrapper.write_text(
        "#!/bin/sh\n"
        f"FAKE_STATE='{state}' exec '{sys.executable}' '{program}' \"$@\"\n")
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return wrapper


COMMON = r'''
import json, os, sys, subprocess, hashlib, time
STATE = os.environ['FAKE_STATE']
def load():
    try:
        with open(STATE) as f: return json.load(f)
    except FileNotFoundError:
        return {}
def save(s):
    tmp = STATE + '.tmp'
    with open(tmp, 'w') as f: json.dump(s, f)
    os.replace(tmp, STATE)
def log_call(s, argv):
    s.setdefault('calls', []).append(argv)
'''


PODMAN = COMMON + r'''
args = sys.argv[1:]
s = load(); log_call(s, args); save(s)
env_home = os.environ.get('XDG_CONFIG_HOME', '')
if args and args[0] == '--connection':
    s['last_connection'] = args[1]; args = args[2:]; save(s)
if args == ['--version']:
    print('podman version 5.8.2'); sys.exit(0)
if args[:2] == ['machine', 'list']:
    print(json.dumps(s.get('machines', []))); sys.exit(0)
if args[:2] == ['machine', 'init']:
    name = args[-1]
    s.setdefault('machines', []).append({'Name': name, 'Running': False, 'xdg_config': env_home})
    save(s); sys.exit(0)
if args[:2] in (['machine', 'start'], ['machine', 'stop']):
    for m in s.get('machines', []):
        if m['Name'] == args[-1]: m['Running'] = args[1] == 'start'
    save(s); sys.exit(0)
if args[:1] == ['info']:
    print(json.dumps({'host': {'arch': s.get('arch', 'arm64'), 'os': 'linux'}, 'version': {'Version': '5.8.2'}})); sys.exit(0)
if args[:1] == ['build']:
    tag = args[args.index('-t') + 1]
    s.setdefault('images', {})[tag] = 'sha256:' + 'b' * 64
    save(s); print('built'); sys.exit(0)
if args[:2] == ['image', 'inspect']:
    tag = args[2]
    image = s.get('images', {}).get(tag)
    if image is None: sys.exit(125)
    print(json.dumps([{'Id': image[7:], 'Digest': 'sha256:' + 'c' * 64, 'Architecture': 'arm64', 'Os': 'linux'}])); sys.exit(0)
containers = s.setdefault('containers', {})
def find(ident):
    for cid, c in containers.items():
        if ident in (cid, c['Name']): return cid, c
    return None, None
if args[:1] == ['create']:
    name = args[args.index('--name') + 1]
    if find(name)[0]: print('name in use', file=sys.stderr); sys.exit(125)
    labels = {}; mounts = []; env = {}; i = 1; platform = None; cpus = memory = pids = None; workdir = None
    while i < len(args) and args[i].startswith('-'):
        a = args[i]
        if a == '--label': k, v = args[i+1].split('=', 1); labels[k] = v; i += 2
        elif a == '-v': mounts.append(args[i+1]); i += 2
        elif a == '-e': k, v = args[i+1].split('=', 1); env[k] = v; i += 2
        elif a == '--platform': platform = args[i+1]; i += 2
        elif a == '--cpus': cpus = float(args[i+1]); i += 2
        elif a == '--memory': memory = int(args[i+1].rstrip('m')) * 1024**2; i += 2
        elif a == '--pids-limit': pids = int(args[i+1]); i += 2
        elif a == '-w': workdir = args[i+1]; i += 2
        elif a in ('--name', '--pull', '--network', '--security-opt', '--cap-drop', '--cidfile', '--user'): i += 2
        else: i += 1
    image = args[i]; argv = args[i+1:]
    cid = hashlib.sha256((name + str(time.time())).encode()).hexdigest()
    containers[cid] = {'Name': name, 'labels': labels, 'mounts': mounts, 'env': env, 'image': image,
                       'argv': argv, 'platform': platform, 'workdir': workdir,
                       'host': {'NanoCpus': int(cpus * 1e9) if cpus else 0, 'Memory': memory, 'PidsLimit': pids},
                       'status': 'created', 'exit': 0, 'log': ''}
    save(s); print(cid); sys.exit(0)
if args[:1] == ['run']:
    i = 1; mounts = []; name = None; workdir = None; env = {}
    while i < len(args) and args[i].startswith('-'):
        a = args[i]
        if a == '--rm': i += 1; continue
        if a == '-v': mounts.append(args[i+1])
        elif a == '--name': name = args[i+1]
        elif a == '-w': workdir = args[i+1]
        elif a == '-e': k, v = args[i+1].split('=', 1); env[k] = v
        i += 2
    s.setdefault('runs', []).append({'name': name, 'mounts': mounts, 'image': args[i], 'argv': args[i+1:], 'env': env})
    save(s)
    full = dict(os.environ); full.update(env)
    p = subprocess.run(args[i+1:], cwd=workdir, env=full)
    sys.exit(p.returncode)
if args[:1] == ['start']:
    cid, c = find(args[-1])
    if cid is None: sys.exit(125)
    if s.get('hold'):
        c['status'] = 'running'; save(s); sys.exit(0)
    table = []
    for m in c['mounts']:
        host, guest = m.split(':')[:2]; table.append((guest, host))
    def tr(x):
        for guest, host in sorted(table, key=lambda t: -len(t[0])):
            x = x.replace(guest, host)
        return x
    env = dict(os.environ); env.update({k: tr(v) for k, v in c['env'].items()})
    cwd = tr(c['workdir']) if c['workdir'] else None
    p = subprocess.run([tr(a) for a in c['argv']], capture_output=True, text=True, env=env, cwd=cwd)
    c['status'] = 'exited'; c['exit'] = p.returncode; c['log'] = p.stdout + p.stderr
    save(s); sys.exit(0)
if args[:2] == ['container', 'exists']:
    sys.exit(0 if find(args[2])[0] else 1)
if args[:2] == ['container', 'inspect']:
    cid, c = find(args[2])
    if cid is None: sys.exit(125)
    image_id = s.get('image_id', 'a' * 64)
    digest = c['image'].split('@', 1)[1] if '@' in c['image'] else ''
    print(json.dumps([{'Id': cid, 'Name': c['Name'], 'Image': image_id, 'ImageDigest': digest,
        'Config': {'Labels': c['labels']}, 'HostConfig': c['host'],
        'State': {'Status': c['status'], 'Running': c['status'] == 'running', 'ExitCode': c['exit'],
                  'Pid': 4242 if c['status'] == 'running' else 0}}]))
    sys.exit(0)
if args[:1] == ['logs']:
    cid, c = find(args[-1]); print(c['log'], end=''); sys.exit(0)
if args[:1] == ['stop']:
    cid, c = find(args[-1])
    if c['status'] == 'running': c['status'] = 'exited'; c['exit'] = 143
    save(s); sys.exit(0)
if args[:1] == ['rm']:
    cid, c = find(args[-1]); containers.pop(cid, None); save(s); sys.exit(0)
print('unsupported fake podman call: ' + ' '.join(args), file=sys.stderr); sys.exit(2)
'''


MAGNUS = COMMON + r'''
args = sys.argv[1:]
s = load(); log_call(s, args)
jobs = s.setdefault('jobs', {})
save(s)
if args == ['--version']:
    print('magnus-sdk 0.8.2'); sys.exit(0)
if args[:1] == ['config']:
    print('Current:  station-a  https://magnus.example  token=sk-SECRETSECRETSECRET'); sys.exit(0)
if args[:1] == ['submit']:
    blueprint = args[1]; rest = args[args.index('--') + 1:] if '--' in args else []
    params = {}
    for i in range(0, len(rest), 2): params[rest[i].lstrip('-')] = rest[i + 1]
    jid = s.get('next_id', 'a1b2c3d4e5f60718')
    jobs[jid] = {'blueprint': blueprint, 'params': params, 'status': s.get('initial_status', 'completed'),
                 'owner': 'me', 'task_name': '[ravel] ' + params.get('ravel_tag', '')}
    save(s)
    print('MAGNUS token sk-LEAKEDLEAKEDLEAKED')
    print('Job submitted: ' + jid); sys.exit(0)
if args[:1] == ['status']:
    j = jobs.get(args[1])
    if j is None: sys.exit(3)
    print(json.dumps({'id': args[1], 'status': j['status'], 'blueprint': j['blueprint'], 'task_name': j['task_name']}))
    sys.exit(0)
if args[:1] == ['logs']:
    print('step 1\nstep 2 token sk-ABCDEFGHIJKL\n', end=''); sys.exit(0)
if args[:2] == ['job', 'result']:
    j = jobs[args[2]]
    print(json.dumps({'success': j['status'] == 'completed', 'message': 'done',
                      'action': s.get('action', 'magnus receive magnus-secret:abc123 --output out')}))
    sys.exit(0)
if args[:1] == ['receive']:
    secret = args[1]; target = args[args.index('--output') + 1]
    if os.path.exists(target):
        import shutil; shutil.rmtree(target)
    os.makedirs(target)
    for name, text in s.get('payload', {'result.json': '{"nevents": 100, "cross_section_pb": 1.5}'}).items():
        with open(os.path.join(target, name), 'w') as f: f.write(text)
    s['received'] = s.get('received', []) + [secret]; save(s); sys.exit(0)
if args[:1] == ['kill']:
    jobs[args[1]]['status'] = 'killed'; save(s); sys.exit(0)
if args[:1] == ['jobs']:
    rows = [{'id': k, **{x: v[x] for x in ('blueprint', 'status', 'task_name', 'owner')}} for k, v in jobs.items()]
    rows += s.get('foreign_jobs', [])
    print(json.dumps(rows)); sys.exit(0)
print('unsupported fake magnus call: ' + ' '.join(args), file=sys.stderr); sys.exit(2)
'''


CONDOR = COMMON + r'''
name = os.path.basename(sys.argv[0]).replace('_', '-')
prog = os.path.basename(os.environ.get('FAKE_PROG', ''))
args = sys.argv[1:]
s = load(); log_call(s, [os.environ['FAKE_PROG']] + args); save(s)
jobs = s.setdefault('jobs', {})
p = os.environ['FAKE_PROG']
if p == 'condor_submit':
    sub = args[-1]; text = open(sub).read()
    fields = dict(l.split(' = ', 1) for l in text.splitlines() if ' = ' in l)
    cid = str(100 + len(jobs))
    tag = fields['+RavelTag'].strip('"')
    if os.environ.get('FAKE_HOLD') == '1':
        jobs[cid] = {'status': 2, 'exit': None, 'tag': tag}
    else:
        r = subprocess.run(['/bin/sh', fields['executable']], cwd=fields['initialdir'])
        jobs[cid] = {'status': 4, 'exit': r.returncode, 'tag': tag}
    save(s); print(f'{cid}.0 - {cid}.0'); sys.exit(0)
if p in ('condor_q', 'condor_history'):
    if '-constraint' in args:
        tag = args[args.index('-constraint') + 1].split('"')[1]
        for k, j in jobs.items():
            if j['tag'] == tag and (p == 'condor_history' or j['status'] in (1, 2)): print(k)
        sys.exit(0)
    cid = args[0].split('.')[0]; j = jobs.get(cid)
    if j is None: sys.exit(0)
    if p == 'condor_q' and j['status'] not in (1, 2, 5): sys.exit(0)
    print(f"{j['status']} {j['exit'] if j['exit'] is not None else 'undefined'} {j['tag']}"); sys.exit(0)
if p == 'condor_rm':
    jobs[args[0].split('.')[0]]['status'] = 3; save(s); sys.exit(0)
if p == 'sbatch':
    script = args[-1]; text = open(script).read()
    tag = [l.split('=', 1)[1] for l in text.splitlines() if l.startswith('#SBATCH --job-name=')][0]
    jid = str(5000 + len(jobs))
    if os.environ.get('FAKE_HOLD') == '1':
        jobs[jid] = {'state': 'RUNNING', 'exit': '0:0', 'tag': tag}
    else:
        r = subprocess.run(['/bin/sh', script], cwd=os.path.dirname(script))
        jobs[jid] = {'state': 'COMPLETED' if r.returncode == 0 else 'FAILED', 'exit': f'{r.returncode}:0', 'tag': tag}
    save(s); print(jid); sys.exit(0)
if p == 'squeue':
    if '-n' in args:
        tag = args[args.index('-n') + 1]
        for k, j in jobs.items():
            if j['tag'] == tag and j['state'] in ('PENDING', 'RUNNING'): print(k)
        sys.exit(0)
    jid = args[args.index('-j') + 1]; j = jobs.get(jid)
    if j and j['state'] in ('PENDING', 'RUNNING'): print(f"{j['state']}|{j['tag']}")
    sys.exit(0)
if p == 'sacct':
    if '--name' in args:
        tag = args[args.index('--name') + 1]
        for k, j in jobs.items():
            if j['tag'] == tag: print(k)
        sys.exit(0)
    jid = args[args.index('-j') + 1]; j = jobs.get(jid)
    if j: print(f"{j['state']}|{j['exit']}|{j['tag']}")
    sys.exit(0)
if p == 'scancel':
    jobs[args[0]]['state'] = 'CANCELLED'; save(s); sys.exit(0)
sys.exit(2)
'''


def install_scheduler(bin_dir, state):
    paths = {}
    for prog in ('condor_submit', 'condor_q', 'condor_history', 'condor_rm', 'sbatch', 'squeue', 'sacct', 'scancel'):
        program = Path(bin_dir) / '_scheduler_fake.py'
        Path(bin_dir).mkdir(parents=True, exist_ok=True)
        program.write_text(CONDOR)
        wrapper = Path(bin_dir) / prog
        wrapper.write_text("#!/bin/sh\n"
                           f"FAKE_PROG='{prog}' FAKE_STATE='{state}' exec '{sys.executable}' '{program}' \"$@\"\n")
        wrapper.chmod(0o755)
        paths[prog] = wrapper
    return paths


def path_with(bin_dir):
    return str(bin_dir) + os.pathsep + os.environ.get('PATH', '/usr/bin:/bin')
