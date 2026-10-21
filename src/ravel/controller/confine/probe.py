"""Inventory probes: what a worker or a launch can actually reach, compared with what was admitted.

``probe(kind, target)`` runs an inert inventory program under the very confinement the worker
or launch gets and reports the observed tools, writable mounts, environment names and
network. ``target['admitted']`` names the admitted sets; any difference is listed and
``equal`` is false, so the step holds before the real start. The result is the
receipt's ``tool_inventory`` entry for that start.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile

from ravel.workflow import sandbox as worker_sandbox

from . import environment as envmod
from . import launcher
from . import locations as loc
from . import worker

INVENTORY = r'''
import json, os, socket, sys, subprocess, selectors, time, signal
spec = json.loads(sys.argv[1])
writable = []
for directory in spec['candidates']:
    name = os.path.join(directory, '.ravel-inventory-' + spec['nonce'])
    try:
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        continue
    os.close(fd)
    os.unlink(name)
    writable.append(directory)
network = 'none'
try:
    s = socket.socket()
except OSError:
    s = None  # the sandbox refuses network sockets outright
if s is not None:
    s.settimeout(2)
    try:
        s.connect(('127.0.0.1', spec['port']))
        network = 'host-loopback'
    except OSError:
        pass
    finally:
        s.close()
result = {'writable': writable, 'env_names': sorted(os.environ), 'network': network,
          'tools': [], 'mcp_observed': False, 'mcp_error': 'missing actual MCP command'}
# Names this interpreter adds by itself: a child started with an empty environment inherits none.
if spec.get('interpreter_names'):
    try:
        child = subprocess.run([sys.executable, '-I', '-S', '-B', '-c',
                                'import json, os; print(json.dumps(sorted(os.environ)))'],
                               env={}, capture_output=True, text=True, timeout=10)
        own = json.loads(child.stdout.strip().splitlines()[-1]) if child.returncode == 0 else None
        result['interpreter_env_names'] = own if isinstance(own, list) and all(isinstance(n, str) for n in own) else None
    except Exception:
        result['interpreter_env_names'] = None
issuer_key = os.path.join(spec['issuer'], 'issuer.key')
try:
    with open(issuer_key, 'rb') as stream: stream.read(1)
    result['issuer_read_denied'] = False
except OSError:
    result['issuer_read_denied'] = True
# Use a fresh private scratch source. If a broken boundary allows this operation, the
# qualification fails; the real issuer is never used as a writable probe destination.
source = os.path.join(writable[0] if writable else os.environ.get('TMPDIR', os.environ.get('HOME', os.getcwd())),
                      '.issuer-probe-' + spec['nonce'])
result['issuer_replace_denied'] = True
try:
    with open(source, 'w') as stream: stream.write('inert')
    try:
        os.rename(source, os.path.join(spec['issuer'], '.negative-probe-' + spec['nonce']))
        result['issuer_replace_denied'] = False
    except OSError:
        pass
except OSError:
    pass  # A worker with no writable mount cannot prepare a replacement either.
finally:
    try: os.unlink(source)
    except OSError: pass
if spec.get('mcp_command'):
    process = None
    try:
        env = {**os.environ, **spec.get('mcp_env', {})}
        result['env_names'] = sorted(env)
        process = subprocess.Popen(spec['mcp_command'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, env=env, start_new_session=True)
        os.set_blocking(process.stdin.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline, buffer, received = time.monotonic() + 8, b'', 0
        def send(value):
            payload = (json.dumps(value) + '\n').encode()
            if len(payload) > 4096 or os.write(process.stdin.fileno(), payload) != len(payload):
                raise ValueError('MCP request pipe blocked or exceeds limit')
        def request(ident, method, params):
            global buffer, received
            send({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params})
            while True:
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    reply = json.loads(line)
                    if reply.get('id') == ident:
                        if 'error' in reply or not isinstance(reply.get('result'), dict):
                            raise ValueError('MCP request refused or malformed')
                        return reply['result']
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise ValueError('MCP response timeout')
                block = os.read(process.stdout.fileno(), 65536)
                received += len(block)
                if not block or received > 1048576:
                    raise ValueError('MCP response closed or exceeds limit')
                buffer += block
        request(1, 'initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                                 'clientInfo': {'name': 'ravel-inventory', 'version': '1'}})
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        tools, cursor = [], None
        for page in range(32):
            reply = request(page + 2, 'tools/list', {'cursor': cursor} if cursor else {})
            entries = reply.get('tools')
            if not isinstance(entries, list) or any(not isinstance(t, dict) or
                    not isinstance(t.get('name'), str) or not t['name'] for t in entries):
                raise ValueError('malformed MCP tool inventory')
            tools.extend(t['name'] for t in entries)
            cursor = reply.get('nextCursor')
            if not cursor:
                break
            if not isinstance(cursor, str) or len(cursor) > 1024:
                raise ValueError('malformed MCP cursor')
        else:
            raise ValueError('MCP page limit exceeded')
        result.update(tools=sorted(set(tools)), mcp_observed=True, mcp_error=None)
    except Exception as error:
        result['mcp_error'] = type(error).__name__ + ': MCP inventory failed'
    finally:
        if process is not None:
            process.stdin.close()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                process.wait(timeout=2)
        if 'selector' in globals():
            selector.close()
print(json.dumps(result))
'''
ADMITTED_KEYS = frozenset({'tools', 'writable', 'env_names', 'network', 'read_roots'})


def _candidates(target, extra):
    """Directories whose writability matters: the declared ones and the protected ones."""
    paths = [Path(p) for p in extra]
    paths += [loc.package_root(), *loc.interpreter_roots(), *loc.account_homes()]
    paths += [p for p in loc.custody_roots() if p.is_dir()]
    run_dir = target.get('run_dir')
    if run_dir:
        paths += [p for p in loc.governed_paths(run_dir) if p.is_dir()] + [Path(run_dir)]
    return [str(loc.real(p)) for p in dict.fromkeys(paths) if p.is_dir()]


def _compare(observed, admitted):
    if admitted is None:
        if observed.get('kind') != 'worker':
            return None, []
        admitted = {}
    if not isinstance(admitted, dict) or set(admitted) - ADMITTED_KEYS:
        raise ValueError('an admitted inventory names ' + ', '.join(sorted(ADMITTED_KEYS)))
    differences = []
    if observed.get('kind') == 'worker':
        for key in sorted({'tools', 'writable', 'env_names', 'network'} - set(admitted)):
            differences.append({'field': key, 'reason': 'missing admitted field'})
        if not observed.get('mcp_observed'):
            differences.append({'field': 'tools', 'reason': observed.get('mcp_error', 'actual MCP observation missing')})
    for key, value in sorted(admitted.items()):
        seen = observed.get(key)
        if isinstance(value, list):
            extra, missing = sorted(set(seen or []) - set(value)), sorted(set(value) - set(seen or []))
            if extra:
                differences.append({'field': key, 'unadmitted': extra})
            if missing:
                differences.append({'field': key, 'absent': missing})
        elif seen != value:
            differences.append({'field': key, 'admitted': value, 'observed': seen})
    return not differences, differences


def _listener():
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    server.settimeout(0.2)
    return server


def _reached(server):
    try:
        server.accept()[0].close()
        return True
    except (socket.timeout, OSError):
        return False


def _launch(target):
    spec = {k: v for k, v in target.items() if k not in ('admitted', 'tools')}
    nonce = secrets.token_hex(6)
    server = _listener()
    try:
        plan = launcher.prepare({**spec, 'argv': [sys.executable, '-I', '-S', '-B', '-c', INVENTORY]})
        extra = [*plan.record.get('writable', []), *plan.record.get('new_output_directories', []),
                 *([str(plan.work_area.parent)] if plan.work_area is not None and plan.work_area.parent.is_dir() else [])]
        plan.argv = [*plan.argv, json.dumps({'candidates': _candidates(target, extra), 'nonce': nonce,
                                             'port': server.getsockname()[1], 'issuer': str(loc.issuer_root())})]
        process = launcher.start(plan, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            out, err = process.communicate(timeout=60)
        finally:
            finished = launcher.finish(plan)
        if process.returncode != 0:
            raise ValueError('launch inventory probe failed: ' + err.decode(errors='replace').strip()[-500:])
        seen = json.loads(out.decode().strip().splitlines()[-1])
        if _reached(server):
            seen['network'] = 'host-loopback'
        scratch = plan.record.get('scratch')
        seen['writable'] = sorted(p for p in seen['writable'] if not scratch or not loc.within(Path(p), [Path(scratch)]))
        observed = {'kind': 'launch', 'backend': plan.record.get('backend'), 'class': plan.record.get('kind'),
                    'tools': sorted(target.get('tools') or [plan.argv[0]]), 'read_roots': plan.record.get('read_roots', []),
                    'writable': seen['writable'], 'env_names': sorted(n for n in seen['env_names']
                                                                       if n not in envmod.SCRATCH and n != envmod.CUSTODY),
                    'network': seen['network'], 'work_area': plan.record.get('work_area'),
                    'issuer_read_denied': seen.get('issuer_read_denied') is True,
                    'issuer_replace_denied': seen.get('issuer_replace_denied') is True,
                    'quarantined': finished['quarantined'] if finished else []}
    finally:
        server.close()
    return observed


def _worker(target):
    workspace = Path(target['workspace'])
    home = worker.private_home(workspace, target.get('home'))
    mcp = target.get('mcp_command')
    if mcp is not None and (not isinstance(mcp, list) or not mcp or
            any(not isinstance(v, str) or '\0' in v for v in mcp) or not Path(mcp[0]).is_absolute()):
        raise ValueError('mcp_command requires absolute executable argv')
    mcp_env = target.get('mcp_env', {})
    if not isinstance(mcp_env, dict) or any(not isinstance(k, str) or not isinstance(v, str) or
            '=' in k or '\0' in k + v for k, v in mcp_env.items()):
        raise ValueError('mcp_env must contain committed string values')
    nonce = secrets.token_hex(6)
    server = _listener()
    try:
        argv = [sys.executable, '-I', '-S', '-B', '-c', INVENTORY]
        candidates = _candidates(target, [workspace / 'outputs', workspace / 'scratch', workspace / 'inputs',
                                          workspace, *(target.get('writable') or []), *target.get('extra_candidates', []),
                                          *([home] if home else [])])
        argv.append(json.dumps({'candidates': candidates, 'nonce': nonce, 'port': server.getsockname()[1],
                                'mcp_command': mcp, 'mcp_env': mcp_env, 'issuer': str(loc.issuer_root()),
                                'interpreter_names': True}))
        read_paths = target.get('read_paths') or list(dict.fromkeys([*worker_sandbox.runtime_paths(argv),
                    *(worker_sandbox.runtime_paths(mcp) if mcp else [])]))
        unsandboxed = target.get('unsandboxed') is True and worker_sandbox.available() is None
        # The operator's restricted unsandboxed reviewer fallback starts its worker without the OS boundary; the probe
        # then observes exactly that (no wrapper), so what it can reach is measured, not assumed.
        command = (list(argv) if unsandboxed else
                   worker.command(workspace, argv, read_paths=read_paths,
                                  protected=target.get('protected', ()), home=home, writable=target.get('writable'),
                                  network=target.get('network')))
        env = dict(target.get('env') or {'PATH': '/usr/bin:/bin', 'HOME': str(workspace / 'scratch')})
        done = subprocess.run(command, cwd=workspace, env=env, capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise ValueError('worker inventory probe failed: ' + done.stderr.strip()[-500:])
        seen = json.loads(done.stdout.strip().splitlines()[-1])
        if _reached(server):
            seen['network'] = 'host-loopback'
        # Names the measuring interpreter adds by itself (a macOS Python's CoreFoundation start adds
        # ``__CF_USER_TEXT_ENCODING``), absent from what the probe was given, are not exposure. An
        # unavailable measurement excludes nothing.
        own = set(seen.get('interpreter_env_names') or ()) - set(env) - set(mcp_env if mcp else ())
        egress = worker_sandbox.egress(target.get('network'))
        observed = {'kind': 'worker', 'backend': worker_sandbox.available(), 'tools': seen['tools'],
                    'declared_tools': sorted(target.get('tools') or []),
                    'mcp_observed': seen['mcp_observed'], 'mcp_error': seen['mcp_error'],
                    'read_roots': sorted(str(p) for p in read_paths), 'writable': sorted(seen['writable']),
                    'issuer_read_denied': seen.get('issuer_read_denied') is True,
                    'issuer_replace_denied': seen.get('issuer_replace_denied') is True,
                    'env_names': sorted(n for n in seen['env_names'] if n not in own),
                    'interpreter_env_names': sorted(own & set(seen['env_names'])),
                    'network': seen['network'] if seen['network'] != 'none' or egress == 'none' else egress,
                    'egress_label': {'none': 'none', 'tcp-443': 'worker egress: any TCP 443 host'}.get(
                        egress, 'worker egress: unrestricted (no TCP port rules on this kernel; UDP unfiltered)'),
                    'endpoint_restricted': False,
                    'tcp_restriction': 'port-only' if egress == 'tcp-443' else egress,
                    'non_tcp_internet': ('unfiltered' if target.get('network') == 'provider'
                                         and worker_sandbox.available() == 'linux' else 'denied'),
                    'name_resolution': ('none' if target.get('network') != 'provider' else
                                        'system resolver service' if worker_sandbox.available() == 'macos'
                                        else 'direct DNS permitted; UDP unfiltered')}
        if unsandboxed:
            # Nothing confines the writable set or the network: they compare as ``unconfined``; what the probe
            # actually reached is kept beside them.
            observed.update(unsandboxed=True, writable_observed=observed['writable'], writable='unconfined',
                            network_observed=observed['network'], network='unconfined',
                            egress_label='worker egress: unconfined (no OS sandbox)')
    finally:
        server.close()
    return observed


def probe(kind, target):
    """Observe a worker's or a launch's actual inventory and compare it with ``target['admitted']``."""
    if kind not in ('worker', 'launch') or not isinstance(target, dict):
        raise ValueError('probe kind is worker or launch, with a target object')
    observed = _launch(target) if kind == 'launch' else _worker(target)
    equal, differences = _compare(observed, target.get('admitted'))
    if observed.get('unsandboxed') is True:
        # A same-uid process without the OS sandbox can read the issuer key (``issuer`` records that risk); the
        # restricted reviewer has no tool that reaches it, and the observation is kept, never treated as denied.
        observed['issuer_exposure'] = {k: observed.get(k) for k in ('issuer_read_denied', 'issuer_replace_denied')}
    else:
        for field in ('issuer_read_denied', 'issuer_replace_denied'):
            if observed.get(field) is not True:
                differences.append({'field': field, 'reason': 'issuer denial probe failed'})
                equal = False
    observed['equal'], observed['differences'] = equal, differences
    from . import runs
    run_id = (target.get('controller') or {}).get('run_id')
    owned = runs.owner_of(target['run_dir']) if target.get('run_dir') else None
    if run_id or owned:
        runs.store(run_id or owned[0]).append('tool-inventory', observed)
    return observed
