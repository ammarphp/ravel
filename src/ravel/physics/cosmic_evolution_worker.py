"""Admitted HPC-site transport and pre-payload rank handshake, stdlib only.

No allocation submission, remote SSH or unobserved group signaling. Controller
schemas/runtime source are explicit inputs. PIDFD targets only the exact local
client; distributed cleanup uses only the observed owned JOB.STEP. Failures and
ambiguous cleanup remain in the ordinary attempt output.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = 'ravel.physics'
from ravel.workflow.state_io import atomic_json
from ravel.workflow.slurm_owned_step import OwnedStep
from ravel.physics import cosmic_evolution_core as core


def _document(path, sha=None, *, capture=None):
    from ravel.workflow.operation_resources import document_pin
    p = document_pin(path)
    if sha is not None and p['sha256'] != sha: raise ValueError('exact consumed rank document changed')
    raw = p['text'].encode()
    if capture is not None:
        capture.read({'path':str(Path(path).absolute()),'sha256':p['sha256'],'size':len(raw)},text=True)
    return core.loads(raw)


def _admission(rundir, *, parent=False):
    """A rank validates delegated metadata, never impersonates the local worker.

    Only the actual parent invokes the unchanged live PID admission. Remote
    ranks revalidate the approved attempt and exact parent registration on the
    shared filesystem, then require the parent's fresh step acknowledgement.
    This is not a remote process-liveness or instantaneous revocation proof.
    """
    from ravel.workflow import science, execution, physics_review
    rd = science.root(rundir)
    if parent: science.verify_worker(rd)
    with science._validation_scope(rd) as session:
        p = science.verify_plan(rd, approved=True, _session=session)
        stage, binding, budget = science._selected(rd, p, _session=session)
        attempt = session.read_document(rd / 'execution_attempt.json')
        state = session.read_document(rd / execution.STATE_NAME)
        record = state.get('stages', {}).get('science', {})
        context = {'stage_spec': physics_review._stage_spec(rd, {**stage, 'inputs': binding['inputs']}),
                   'max_seconds': budget, 'review_action': 'correction' if attempt['attempt'] > 1 else 'bulk'}
        science._check_launch_selection(rd, {'stage': stage, 'binding': binding, 'max_seconds': budget},
                                       'science', stage['command'], context, session)
        if (record.get('status') != 'running' or record.get('fingerprint') != binding['fingerprint'] or
                type(record.get('supervisor_pid')) is not int or record['supervisor_pid'] <= 0 or
                type(record.get('child_pid')) is not int or record['child_pid'] <= 0 or
                type(record.get('child_identity')) is not str or not record['child_identity']):
            raise ValueError('delegation requires the exact currently registered admitted parent attempt')
        token = {'attempt': attempt['attempt'], 'plan_sha256': session.hash_file(rd / science.PLAN),
                 'approval_sha256': session.hash_file(rd / science.APPROVAL),
                 'attempt_sha256': session.hash_file(rd / 'execution_attempt.json'),
                 'stage_fingerprint': binding['fingerprint'], 'output_directory': stage['outputs'][0],
                 'worker': {k: record[k] for k in ('supervisor_pid', 'child_pid', 'child_identity')}}
        proposal = {**p, 'stages': [stage], 'stage_binding': binding, 'max_seconds': budget,
                    'output_directory': stage['outputs'][0], 'attempt': attempt['attempt']}
    return proposal, token


def derived_payload(case_out, declaration, config_digest, limits):
    """Consume an earlier build's actual complete product receipt, no old binary."""
    base = Path(case_out) / core.name(declaration['build_phase'])
    receipt = base / 'build-products.json'
    from ravel.workflow.operation_resources import document_pin
    observed = document_pin(receipt); value = core.loads(observed['text'].encode())
    core.keys(value, ('schema_version', 'phase', 'configuration_sha256', 'inventory'), 'complete build product receipt')
    if type(value['schema_version']) is not int or value['schema_version'] != 1 or value['phase'] != declaration['build_phase'] or value['configuration_sha256'] != config_digest:
        raise ValueError('derived binary source/build prescription differs')
    current = core.output_inventory(base / 'native', limits)
    if current != value['inventory']: raise ValueError('current complete build products differ')
    rows = [r for r in current if r['path'] == declaration['path']]
    if len(rows) != 1: raise ValueError('exact declared built executable missing')
    p = base / 'native' / declaration['path']; row = rows[0]
    return p, {'path': str(p), 'sha256': row['sha256'], 'size': row['size']}, {
        'path': str(receipt), 'sha256': observed['sha256'], 'size': len(observed['text'].encode())}


def ic_product(case, case_out, writer, config_digest, capture, limits):
    declared = case['ic']
    if declared is None: raise ValueError('complete IC population is required for native evolution')
    if 'generated_phase' not in declared:
        core.binary_ic(capture, declared, writer)
        return declared
    phase_out = Path(case_out) / declared['generated_phase']
    receipt = _document(phase_out / 'ic-products.json')
    core.keys(receipt, ('schema_version', 'configuration_sha256', 'phase', 'products'), 'full fresh IC receipt')
    current = core.generated_ic(phase_out / 'native', declared['file_list'], declared['shape'], writer, limits)
    if (type(receipt['schema_version']) is not int or receipt['schema_version'] != 1 or
            receipt['phase'] != declared['generated_phase'] or receipt['configuration_sha256'] != config_digest or receipt['products'] != current):
        raise ValueError('current whole generated ICs/receipt/source differ')
    return current['declaration']


def handoff_ic(case, phase, case_out, work, writer, config_digest, capture, limits):
    """Exact whole native FileList/chunk copy; no invented FileList rewrite."""
    declared = ic_product(case, case_out, writer, config_digest, capture, limits)
    target = phase['ic_handoff']
    if target is None or len(target['chunks_to']) != len(declared['chunks']):
        raise ValueError('complete source-defined IC scratch handoff required')
    original = [declared['file_list'], *declared['chunks']]
    destinations = [target['file_list_to'], *target['chunks_to']]
    copied = core.Capture(work, limits); pins = []
    source = core.Capture(Path(declared['reader_base']), limits)
    for pin, name in zip(original, destinations):
        p, _ = source.read(pin); q = work / core.relative(name)
        q.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, q)
        new = {**pin, 'path': str(q)}; copied.read(new); pins.append(new)
    new = {'file_list': pins[0], 'chunks': pins[1:], 'shape': declared['shape'], 'reader_base': str(work)}
    core.binary_ic(copied, new, writer)
    rows = [r for r in phase['copies'] if r['file'] == case['nyx_card']]
    if len(rows) != 1 or not phase['argv'] or phase['argv'][0] != rows[0]['to']:
        raise ValueError('native Nyx argv must select its exact copied original card')
    _, raw = copied.read({**case['nyx_card'], 'path': str(work / rows[0]['to'])}, text=True)
    from ravel.physics.cosmic_evolution import _effective
    values = _effective(core.card(raw))
    filename = values.get('nyx.binary_particle_file', '')
    selected = Path(filename); selected = selected if selected.is_absolute() else work / selected
    if values.get('nyx.particle_init_type') != 'BinaryMetaFile' or selected.absolute() != work / target['file_list_to']:
        raise ValueError('original native card/actual reader/FileList association differs; supply a prospective source-bound card')
    source.finish(); copied.finish()
    return {'original': declared, 'scratch': new, 'source_bytes_preserved': True, 'physics_verified': False}


def _copied_inputs(case, phase, work, limits):
    """Authenticate actual consumed scratch inputs against original commitments.

    No corrected cards or transfer names are invented. The native arguments
    select the exact admitted original card/transfer copies; the card is parsed
    from those same authenticated bytes, then held through the last checkpoint.
    """
    copied = core.Capture(work, limits)
    for row in phase['copies']:
        copied.read({**row['file'], 'path':str(Path(work) / core.relative(row['to']))})
    required = ([case['ic_card'],case['transfer']['file']] if phase['kind'] == 'cosmicic'
                else [case['nyx_card']] if phase['kind'] == 'nyx' else [])
    for index, original in enumerate(required):
        rows = [r for r in phase['copies'] if r['file'] == original]
        if len(rows) != 1 or len(phase['argv']) <= index or phase['argv'][index] != rows[0]['to']:
            raise ValueError('native argv must consume each exact admitted card/transfer scratch copy')
        _, raw = copied.read({**original,'path':str(Path(work) / rows[0]['to'])},text=True)
        if index == 0:
            from ravel.physics.cosmic_evolution import _effective
            _effective(core.card(raw))
    copied.finish()
    return copied


def check_handoff_ic(case, phase, case_out, work, writer, config_digest, capture, limits, expected):
    declared = ic_product(case, case_out, writer, config_digest, capture, limits)
    target = phase['ic_handoff']
    if target is None or len(target['chunks_to']) != len(declared['chunks']): raise ValueError('full IC handoff differs')
    pins = [{**p, 'path': str(work / core.relative(q))} for p, q in zip(
        [declared['file_list'], *declared['chunks']], [target['file_list_to'], *target['chunks_to']])]
    new = {'file_list': pins[0], 'chunks': pins[1:], 'shape': declared['shape'], 'reader_base': str(work)}
    actual = {'original': declared, 'scratch': new, 'source_bytes_preserved': True, 'physics_verified': False}
    if actual != expected: raise ValueError('IC handoff does not bind current original products')
    copied = core.Capture(work, limits); core.binary_ic(copied, new, writer); copied.finish()
    return actual


class LocalClient:
    """Finite source-bound client I/O with exact Linux pidfd termination.

    No local-group cleanup claim is returned. The outer ordinary supervisor
    retains its own process accounting; remote step cleanup is separate.
    """
    def __init__(self, argv, cwd, env, max_bytes):
        if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
            raise ValueError('site-local client requires exact Linux pidfd support; no PID/group guess')
        self.root = Path(cwd); self.max_bytes = max_bytes
        self.stdout = (self.root / 'stdout.log').open('xb'); self.stderr = (self.root / 'stderr.log').open('xb')
        self.process = subprocess.Popen(argv, cwd=cwd, env=env, stdout=self.stdout, stderr=self.stderr, start_new_session=True)
        # pidfd_open identifies this still-owned unreaped child, never a PGID.
        self.fd = os.pidfd_open(self.process.pid)
        self.argv = argv

    def poll(self):
        if sum((self.root / n).stat().st_size for n in ('stdout.log', 'stderr.log')) > self.max_bytes:
            raise ValueError('complete client output exceeds declared byte envelope')
        return self.process.poll()

    def close(self, *, stop=False):
        if stop and self.process.poll() is None:
            signal.pidfd_send_signal(self.fd, signal.SIGTERM)
            try: self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                signal.pidfd_send_signal(self.fd, signal.SIGKILL); self.process.wait(timeout=1)
        else: self.process.wait(timeout=1)
        self.stdout.close(); self.stderr.close(); os.close(self.fd)
        return {'pid': self.process.pid, 'returncode': self.process.returncode,
                'leader_reaped': True, 'exact_pidfd_used': True, 'local_group_absence': None}


class Controller:
    def __init__(self, runtime, root, capture, limits, deadline):
        self.runtime = runtime; self.root = Path(root); self.root.mkdir()
        self.capture = capture; self.limits = limits; self.deadline = deadline; self.calls = []
        self.env = dict(os.environ); self.env.update(runtime['environment'])
        self.publications = core.Publications(limits)
        self.returned = core.Capture(self.root, self.publications.limits)

    def invoke(self, argv):
        if len(self.calls) >= self.limits['max_controller_calls'] or time.monotonic() >= self.deadline:
            raise ValueError('prospective controller call/time envelope exhausted')
        directory = self.root / str(len(self.calls)); directory.mkdir()
        row = {'argv': argv, 'status': 'started'}; self.calls.append(row)
        self.publications.json(self.root / 'calls.json', self.calls)
        client = LocalClient(argv, directory, self.env, self.limits['max_controller_bytes'])
        try:
            while client.poll() is None:
                if time.monotonic() >= min(self.deadline, row.setdefault('started_monotonic', time.monotonic()) + 15):
                    raise ValueError('bounded controller query timeout')
                time.sleep(.05)
            receipt = client.close(); row.update(status='returned', receipt=receipt)
            if receipt['returncode'] != 0: raise ValueError('controller command failed; raw outputs retained')
            outputs = {}
            for filename in ('stdout.log','stderr.log'):
                p = core.ordinary(directory / filename); before = p.lstat()
                with p.open('rb') as stream:
                    if core.identity(os.fstat(stream.fileno())) != core.identity(before): raise ValueError('opened controller output changed')
                    raw = stream.read(self.limits['max_controller_bytes'] + 1)
                    if core.identity(os.fstat(stream.fileno())) != core.identity(before): raise ValueError('consumed controller output changed')
                if len(raw) > self.limits['max_controller_bytes'] or core.identity(before) != core.identity(p.lstat()): raise ValueError('controller output consumption changed')
                pin = {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}
                self.returned.read(pin)
                if core.identity(before) != self.returned.files[str(p)]['identity']: raise ValueError('controller output was replaced after consumption')
                outputs[filename] = {'pin':pin,'consumed':raw}
            row['output_pins'] = [outputs[n]['pin'] for n in ('stdout.log','stderr.log')]
            self.capture.check_identities(); self.returned.finish(); self.publications.finish(); return outputs['stdout.log']['consumed']
        except BaseException:
            if not client.stdout.closed: row['receipt'] = client.close(stop=True)
            row['status'] = 'failed'; raise
        finally: self.publications.json(self.root / 'calls.json', self.calls)

    def observe(self, kind, job, step):
        key = 'scancel' if kind == 'cancel' else 'scontrol'
        p, _ = self.capture.read(self.runtime['slurm'][key])
        args = ([str(p), '--quiet', f'{job}.{step}'] if kind == 'cancel' else
                [str(p), '--local', '--json', 'show', 'job' if kind == 'job' else 'step', str(job) if kind == 'job' else f'{job}.{step}'])
        return self.invoke(args)

    def expand_nodes(self, value):
        if type(value) is not str or not value or '\x00' in value or value.startswith('-'):
            raise ValueError('explicit installed compact hostlist required')
        p, _ = self.capture.read(self.runtime['slurm']['scontrol'])
        raw = self.invoke([str(p), '--local', 'show', 'hostnames', value])
        rows = raw.decode('utf-8').splitlines()
        if not rows or len(rows) != len(set(rows)) or any(not r or r.strip() != r for r in rows):
            raise ValueError('complete native expanded node names required')
        return rows


def execute(d, config_path, capture, schemas, out, rundir, *, controller_factory=Controller, client_factory=LocalClient):
    """Actual public source path; tests supply disclosed inert client factories."""
    limits = d['resources']; runtime = d['runtime']; start = time.monotonic()
    _, parent_admission = _admission(rundir, parent=True)
    controller = controller_factory(runtime, Path(out) / 'controller', capture, limits,
                                    start + limits['max_seconds'] + limits['cleanup_seconds'])
    ctl, _ = capture.read(runtime['slurm']['scontrol'])
    if controller.invoke([str(ctl), '--version']).decode().strip() != runtime['version']:
        raise ValueError('actual installed controller version differs')
    config_raw = controller.invoke([str(ctl), '--local', 'show', 'config']).decode('utf-8')
    cluster = [line.split('=', 1)[1].strip() for line in config_raw.splitlines()
               if line.split('=', 1)[0].strip() == 'ClusterName' and '=' in line]
    if cluster != [runtime['allocation']['cluster']]:
        raise ValueError('actual site-local controller cluster differs')
    results = []; phase_observations = []
    writer = capture.json(d['writer_contract'])
    from ravel.workflow.execution import digest
    config_digest = digest(d)
    publications = core.Publications(limits)
    try:
        for case in d['cases']:
            case_out = Path(out) / case['id']; case_out.mkdir()
            phases = []
            for phase in case['phases']:
                phase_out = case_out / phase['id']; phase_out.mkdir(); handshakes = phase_out / 'handshake'; handshakes.mkdir()
                work = phase_out / 'native'; work.mkdir()
                phase_observed = core.Capture(phase_out, publications.limits); phase_observations.append(phase_observed)
                for row in phase['copies']:
                    source, _ = capture.read(row['file']); target = work / core.relative(row['to'])
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(source, target)
                    copied = core.Capture(work, limits); copied.read({**row['file'], 'path': str(target)}); copied.finish()
                ic_handoff = None
                if phase['kind'] == 'nyx':
                    ic_handoff = handoff_ic(case, phase, case_out, work, writer, config_digest, capture, limits)
                    publications.json(phase_out / 'ic-handoff.json', ic_handoff)
                elif phase['kind'] == 'cosmicic':
                    for index, source in enumerate((case['ic_card'], case['transfer']['file'])):
                        rows = [r for r in phase['copies'] if r['file'] == source]
                        if len(rows) != 1 or len(phase['argv']) < 3 or phase['argv'][index] != rows[0]['to']:
                            raise ValueError('CosmicIC argv must select exact original card and transfer scratch bytes')
                built_receipt = None
                if 'build_phase' in phase['payload']:
                    from ravel.workflow.execution import digest
                    payload, pin, built_receipt = derived_payload(case_out, phase['payload'], digest(d), limits)
                else:
                    payload, _ = capture.read(phase['payload']); pin = {**phase['payload'], 'path': str(payload)}
                if not os.access(payload, os.X_OK): raise ValueError('exact executable native payload required')
                ownership = OwnedStep(runtime['allocation'], schemas, controller.observe, expand_nodes=controller.expand_nodes)
                ownership.begin(os.getuid(), os.environ.get('SLURM_JOB_ID'), pin)
                nonce = uuid.uuid4().hex
                plan = {'rundir': str(rundir), 'config_path': str(config_path), 'phase_id': phase['id'],
                        'case_id': case['id'], 'nonce': nonce, 'payload': pin, 'argv': phase['argv'],
                        'handshake': str(handshakes), 'native_cwd': str(work), 'ranks': phase['ranks'],
                        'job_id': runtime['allocation']['job_id'], 'uid': runtime['allocation']['uid'],
                        'handshake_seconds': min(limits['handshake_seconds'], phase['max_seconds']), 'payload_seconds': phase['max_seconds'],
                        'build_receipt': built_receipt, 'ic_handoff': ic_handoff, 'parent_admission': parent_admission}
                plan_path = phase_out / 'rank-plan.json'; publications.json(plan_path, plan)
                plan_sha = publications.rows[str(plan_path.absolute())]['pin']['sha256']
                python, _ = capture.read(runtime['python']); srun, _ = capture.read(runtime['slurm']['srun'])
                secs = phase['max_seconds']; clock = f'{secs//3600:02}:{secs//60%60:02}:{secs%60:02}'
                argv = [str(srun), '--jobid=' + str(runtime['allocation']['job_id']), '--kill-on-bad-exit=1',
                        '--nodes=' + str(phase['nodes']), '--ntasks=' + str(phase['ranks']), '--time=' + clock]
                if phase['gpus_per_node']: argv += ['--gpus-per-node=' + str(phase['gpus_per_node'])]
                argv += [str(python), '-I', '-B', str(Path(__file__).absolute()), '--rank', str(plan_path), plan_sha]
                client_out = phase_out / 'client'; client_out.mkdir()
                client = client_factory(argv, client_out, controller.env, limits['max_output_bytes'])
                deadline = min(start + limits['max_seconds'], time.monotonic() + phase['max_seconds'])
                handshake_deadline = min(deadline, time.monotonic() + plan['handshake_seconds'])
                try:
                    paths = [handshakes / f'rank-{i}.json' for i in range(phase['ranks'])]
                    while not all(p.exists() for p in paths):
                        if client.poll() is not None or time.monotonic() >= handshake_deadline:
                            raise ValueError('complete step handshake unavailable before payload; ownership held')
                        time.sleep(.05)
                    rows = [_document(p,capture=phase_observed) for p in paths]
                    ack = ownership.bind(rows, phase['ranks'], nonce, pin)
                    if _admission(rundir, parent=True)[1] != parent_admission:
                        raise ValueError('parent attempt/delegation changed before payload acknowledgement')
                    ack['delegation_sha256'] = digest(parent_admission)
                    scratch = _copied_inputs(case, phase, work, limits)
                    phase_observations.append(scratch)
                    capture.finish(); phase_observed.finish(); publications.finish()
                    if ic_handoff is not None: check_handoff_ic(case, phase, case_out, work, writer, config_digest, capture, limits, ic_handoff)
                    scratch.finish()
                    if time.monotonic() >= handshake_deadline:
                        raise ValueError('parent acknowledgement deadline exhausted before payload release')
                    publications.json(handshakes / 'ack.json', ack)
                    while client.poll() is None:
                        if time.monotonic() >= deadline: raise ValueError('native phase time envelope exhausted')
                        time.sleep(.05)
                    local = client.close()
                    if local['returncode'] != 0: raise ValueError('native client/rank failed')
                    exits = [_document(handshakes / f'exit-{i}.json',capture=phase_observed) for i in range(phase['ranks'])]
                    distributed = ownership.finish(exits)
                    phase_observed.finish(); scratch.finish()
                    if phase['kind'] == 'build':
                        from ravel.workflow.execution import digest
                        publications.json(phase_out / 'build-products.json', {'schema_version': 1, 'phase': phase['id'],
                            'configuration_sha256': digest(d), 'inventory': core.output_inventory(work, limits)})
                    if phase['kind'] == 'cosmicic' and case['ic'] is not None and case['ic'].get('generated_phase') == phase['id']:
                        if not Path(case['ic']['file_list']).is_relative_to(core.relative(phase['argv'][2])):
                            raise ValueError('actual generated FileList is outside original CosmicIC output argv')
                        products = core.generated_ic(work, case['ic']['file_list'], case['ic']['shape'], writer, limits)
                        publications.json(phase_out / 'ic-products.json', {'schema_version': 1, 'configuration_sha256': config_digest,
                            'phase': phase['id'], 'products': products})
                    if built_receipt is not None:
                        derived_payload(case_out, phase['payload'], digest(d), limits)
                    phases.append({'id': phase['id'], 'kind': phase['kind'], 'local_client': local, 'distributed': distributed, 'ic_handoff': ic_handoff})
                except BaseException:
                    cleanup = {'held': True, 'reason': 'step identity not observed'}
                    if ownership.owned is not None:
                        try: cleanup = ownership.cancel()
                        except Exception as error: cleanup = {'held': True, 'reason': str(error)}
                    if not client.stdout.closed: local = client.close(stop=True)
                    publications.json(phase_out / 'failure.json', {'ownership_observations': ownership.evidence, 'cleanup': cleanup,
                                                            'local_group_absence': None, 'payload_released': ownership.owned is not None})
                    raise
                finally: publications.json(case_out / 'phases.json', phases)
            delivery = core.check_outputs(case_out, case['outputs'], limits)
            results.append({'id': case['id'], 'phases': phases, 'delivery': delivery, 'fresh_native_execution': True})
            publications.json(Path(out) / 'native-cases.json', results)
        capture.finish()
        for row in results:
            current = core.output_inventory(Path(out) / row['id'], limits)
            if current != row['delivery']['inventory']: raise ValueError('ending native case output changed')
        for observed in phase_observations: observed.finish()
        publications.finish(); return results
    finally:
        publications.json(Path(out) / 'controller-calls.json', controller.calls)
        publications.finish()
        if hasattr(controller, 'publications'): controller.publications.finish()
        if hasattr(controller, 'returned'): controller.returned.finish()


def rank(plan_path, sha):
    """Source-defined shim: no scientific payload until exact parent ack."""
    plan = _document(plan_path, sha)
    core.keys(plan, ('rundir', 'config_path', 'phase_id', 'case_id', 'nonce', 'payload', 'argv', 'handshake',
                     'native_cwd', 'ranks', 'job_id', 'uid', 'handshake_seconds', 'payload_seconds', 'build_receipt', 'ic_handoff', 'parent_admission'), 'rank plan')
    from ravel.workflow import science
    proposal, admission = _admission(plan['rundir'])
    if admission != plan['parent_admission']: raise ValueError('rank delegation differs from current approved parent attempt')
    spec = science.execution_spec(plan['rundir'])
    if spec['mode'] != 'cosmic-evolution' or science.regular(spec['task']['input'], proposal['base_dir']) != Path(plan['config_path']):
        raise ValueError('rank shim requires exact live ordinary operation')
    from .cosmic_evolution import _capture
    _, d, capture, _, _, _ = _capture(spec['task'], proposal['base_dir'])
    selected = [p for c in d['cases'] if c['id'] == plan['case_id'] for p in c['phases'] if p['id'] == plan['phase_id']]
    if len(selected) != 1: raise ValueError('one exact admitted rank phase required')
    if 'build_phase' in selected[0]['payload']:
        from ravel.workflow.execution import digest
        rd = Path(plan['rundir']).absolute(); case_out = rd / proposal['output_directory'] / 'cosmic-evolution' / plan['case_id']
        actual_payload, actual_pin, actual_receipt = derived_payload(case_out, selected[0]['payload'], digest(d), d['resources'])
        if actual_receipt != plan['build_receipt']: raise ValueError('current built receipt differs')
    else:
        actual_payload, _ = capture.read(selected[0]['payload']); actual_pin = {**selected[0]['payload'], 'path': str(actual_payload)}
        if plan['build_receipt'] is not None: raise ValueError('source executable cannot borrow a build receipt')
    if (actual_pin != plan['payload'] or selected[0]['argv'] != plan['argv'] or selected[0]['ranks'] != plan['ranks'] or
            d['runtime']['allocation']['job_id'] != plan['job_id'] or d['runtime']['allocation']['uid'] != plan['uid'] or
            plan['handshake_seconds'] != min(d['resources']['handshake_seconds'], selected[0]['max_seconds']) or plan['payload_seconds'] != selected[0]['max_seconds']):
        raise ValueError('rank payload/argv/population differs from original admitted input')
    rd = Path(plan['rundir']).absolute(); expected = rd / proposal['output_directory'] / 'cosmic-evolution' / plan['case_id'] / plan['phase_id']
    if Path(plan['handshake']) != expected / 'handshake' or Path(plan['native_cwd']) != expected / 'native': raise ValueError('rank output/handshake destination differs')
    who = int(os.environ['SLURM_PROCID']); job = int(os.environ['SLURM_JOB_ID']); step = int(os.environ['SLURM_STEP_ID'])
    if not 0 <= who < plan['ranks'] or job != plan['job_id'] or os.getuid() != plan['uid']: raise ValueError('rank allocation/UID identity differs')
    publications = core.Publications(d['resources'])
    directory = Path(plan['handshake']); native = Path(plan['native_cwd'])
    if any(p.is_symlink() for p in (directory, *directory.parents, native)): raise ValueError('rank destination aliases refused')
    selected_case = next(c for c in d['cases'] if c['id'] == plan['case_id'])
    if selected[0]['kind'] == 'nyx':
        writer = capture.json(d['writer_contract'])
        from ravel.workflow.execution import digest
        check_handoff_ic(selected_case, selected[0], expected.parent, native, writer, digest(d), capture, d['resources'], plan['ic_handoff'])
    elif plan['ic_handoff'] is not None: raise ValueError('unrelated phase cannot borrow IC handoff')
    scratch = _copied_inputs(selected_case, selected[0], native, d['resources'])
    publications.json(directory / f'rank-{who}.json', {'nonce': plan['nonce'], 'job_id': job, 'step_id': step,
               'uid': os.getuid(), 'rank': who, 'node': socket.gethostname(), 'payload': plan['payload']})
    deadline = time.monotonic() + plan['handshake_seconds']; ack_path = directory / 'ack.json'
    while not ack_path.exists():
        if time.monotonic() >= deadline: raise ValueError('no exact parent handshake; scientific payload never released')
        time.sleep(.05)
    if time.monotonic() >= deadline: raise ValueError('acknowledgement deadline exhausted before consumption')
    external = core.Capture(directory, publications.limits)
    ack = _document(ack_path,capture=external)
    if time.monotonic() >= deadline: raise ValueError('acknowledgement consumed after declared handshake deadline')
    core.keys(ack, ('nonce', 'payload', 'job_id', 'step_id', 'uid', 'start', 'delegation_sha256'), 'owned-step acknowledgement')
    if any(ack[k] != v for k, v in {'nonce': plan['nonce'], 'payload': plan['payload'], 'job_id': job, 'step_id': step, 'uid': os.getuid()}.items()): raise ValueError('foreign acknowledgement')
    from ravel.workflow.execution import digest
    if ack['delegation_sha256'] != digest(admission) or _admission(plan['rundir'])[1] != admission:
        raise ValueError('acknowledged parent delegation changed before payload')
    if plan['build_receipt'] is not None:
        product = core.Capture(actual_payload.parent, d['resources']); product.read(plan['payload']); product.read(plan['build_receipt'], text=True); product.finish()
        derived_payload(case_out, selected[0]['payload'], digest(d), d['resources'])
        payload = actual_payload
    else: payload, _ = capture.read(plan['payload'])
    capture.finish()
    if selected[0]['kind'] == 'nyx':
        check_handoff_ic(selected_case, selected[0], expected.parent, native, writer, digest(d), capture, d['resources'], plan['ic_handoff'])
    scratch.finish(); publications.finish(); external.finish()
    if time.monotonic() >= deadline: raise ValueError('pre-payload handshake/delegation deadline exhausted')
    exit_code = subprocess.call([str(payload), *plan['argv']], cwd=native, env=dict(os.environ))
    publications.json(directory / f'exit-{who}.json', {'rank': who, 'exit_code': exit_code, 'job_id': job, 'step_id': step})
    publications.finish(); scratch.finish()
    return exit_code


def main(argv=None):
    p = argparse.ArgumentParser(); p.add_argument('--rank', action='store_true'); p.add_argument('plan'); p.add_argument('sha256')
    a = p.parse_args(argv)
    if not a.rank: raise ValueError('only an admitted source-bound rank shim is exposed')
    return rank(a.plan, a.sha256)


if __name__ == '__main__': raise SystemExit(main())
