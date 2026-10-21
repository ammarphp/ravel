"""Export a recorded procedure, audit and Snakemake evidence-verification DAG.

One rule maps to each recorded stage attempt or worker invocation. Rules verify
retained evidence; scientific recomputation uses the existing approved site
workflow. Export does not approve, replay or qualify scientific operations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile

from . import agent_audit, env_snapshot, worker_audit
from .site_profiles import write_profiles



def dependency_sources():
    """Source-identity seam consumed by the existing Host reuse boundary."""
    from . import completion_disclosure, submission_export, site_profiles
    from .site_profiles import htcondor
    modules = [sys.modules[__name__], agent_audit, env_snapshot, worker_audit,
               completion_disclosure, submission_export, site_profiles, htcondor]
    return {module.__name__: _source(module.__file__)['sha256'] for module in modules}


def _encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def _write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(_encoded(value))


def _source(path):
    path = Path(path)
    if path.is_symlink(): raise ValueError('procedure source symlink refused')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return {'path': str(path.absolute()), 'sha256': digest.hexdigest(), 'size': path.stat().st_size}



DEFAULT_BYTE_CEILING = 1024 * 1024


def _byte_ceiling(rundir=None):
    """The procedure byte ceiling: the operator's for a controller-owned run, never the environment."""
    from ravel.controller.sink import legacy as sink_legacy
    if rundir is not None and sink_legacy.owner(rundir) is not None:
        ceiling = DEFAULT_BYTE_CEILING
        import importlib
        try:
            authority = importlib.import_module('ravel.controller.authority')
        except ImportError:
            authority = None
        if authority is not None and hasattr(authority, 'operator_config'):
            ceiling = authority.operator_config().get('procedure_byte_ceiling', DEFAULT_BYTE_CEILING)
        if type(ceiling) is not int or ceiling < 0:
            raise ValueError('the operator procedure byte ceiling must be a nonnegative integer')
        return ceiling
    try:
        ceiling = int(os.environ.get('RAVEL_PROCEDURE_BYTE_CEILING', DEFAULT_BYTE_CEILING))
    except ValueError as exc:
        raise ValueError('procedure byte ceiling must be a nonnegative integer') from exc
    if ceiling < 0: raise ValueError('procedure byte ceiling must be a nonnegative integer')
    return ceiling


def _ordinary(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('procedure artifact symlink refused')
    return path


def _check_pin(pin, *, deep=False, base=None):
    path = Path(pin["path"])
    path = _ordinary(path if path.is_absolute() or base is None else Path(base) / path)
    if not path.is_file() or path.stat().st_size != pin['size']:
        raise ValueError('procedure source changed: ' + str(path))
    if deep:
        if pin['sha256'] is None:
            raise ValueError('procedure source has no recorded digest: ' + str(path))
        actual = _source(path)
        if actual['sha256'] != pin['sha256'] or actual['size'] != pin['size']:
            raise ValueError('procedure source changed: ' + str(path))


def _reference(path, binding, ceiling):
    path = _ordinary(path)
    size = binding.get('size', path.stat().st_size)
    sha = binding.get('sha256')
    if sha is not None and (type(sha) is not str or len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha)):
        raise ValueError('recorded artifact digest required')
    if type(size) is not int or size < 0: raise ValueError('recorded artifact size required')
    pin = {'path': str(path), 'sha256': sha, 'size': size}
    if size > ceiling: pin['reference_only'] = True
    _check_pin(pin)
    return pin


def _disclosure_pins(value, root, ceiling):
    """Bind supplied digests without re-reading their referenced data."""
    if type(value) is dict:
        if {'path', 'sha256'} <= value.keys():
            path = Path(value['path']); path = path if path.is_absolute() else root / path
            yield _reference(path, value, ceiling)
        else:
            for child in value.values(): yield from _disclosure_pins(child, root, ceiling)
    elif type(value) is list:
        for child in value: yield from _disclosure_pins(child, root, ceiling)


def _snapshot_pins(root, snapshots, ceiling):
    result = {}
    for value, binding in snapshots.items():
        base = Path(value); base = _ordinary(base if base.is_absolute() else root / base)
        if 'files' not in binding:
            result[str(base)] = _reference(base, binding, ceiling)  # Legacy singleton pin.
            continue
        recorded = set()
        for row in binding['files']:
            name = Path(row['name'])
            if name.is_absolute() or '..' in name.parts: raise ValueError('recorded artifact member escaped')
            path = base if row['name'] == '.' else base / name
            key = str(path)
            if key in recorded: raise ValueError('duplicate recorded artifact member')
            recorded.add(key); result[key] = _reference(path, row, ceiling)
        if not base.exists(): raise ValueError('recorded output changed: ' + str(base))
        observed = {str(p) for p in ([base] if base.is_file() else base.rglob('*')) if p.is_file() or p.is_symlink()}
        if observed != recorded: raise ValueError('recorded output changed: ' + str(base))
    return result


def _files(root, values, bindings, ceiling):
    pins = []; missing = []
    for value in values:
        path = Path(value); path = _ordinary(path if path.is_absolute() else root / path)
        if not path.exists():
            missing.append(str(path)); continue
        files = [path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file() or p.is_symlink())
        for member in files:
            if str(member) in bindings:
                pins.append(bindings[str(member)])
            elif member.stat().st_size > ceiling:
                pins.append(_reference(member, {'sha256': None}, ceiling))
            else:
                pins.append(_source(_ordinary(member)))
    return pins, missing


def _runtime_snapshots(root):
    reader = getattr(env_snapshot, 'runtime_snapshots', None)
    return reader(root) if reader is not None else []


def _replay_template():
    try:
        from . import replay
    except ImportError as exc:
        if exc.name not in (__package__ + '.replay', __package__): raise
        return '# Replay template unavailable: replay.template_text() is not installed. No execution rules.\n'
    return replay.template_text()


def _procedure_status(status):
    if status is None: return 'complete'
    return {'pass': 'complete', 'complete': 'complete', 'completed': 'complete',
            'fail': 'failed', 'failed': 'failed', 'abort': 'aborted', 'aborted': 'aborted'}.get(str(status).lower(), 'incomplete')


def _campaign_runs(root):
    """Consume pinned heads from the parent collector or from a campaign itself."""
    heads = []; pins = []; campaign_roots = []
    collector = root / 'inputs/completion_sources.json'
    if collector.exists():
        pins.append(_source(_ordinary(collector)))
        sources = json.loads(collector.read_text())
        for binding in sources.get('research_cycles', []):
            path = Path(binding['path']); path = _ordinary(path if path.is_absolute() else root / path)
            if path.name != 'head.json': raise ValueError('current research head required')
            actual = _source(path)
            if actual['sha256'] != binding['sha256'] or 'size' in binding and actual['size'] != binding['size']:
                raise ValueError('campaign head source changed')
            heads.append(path)
    if (root / 'head.json').exists(): heads.append(root / 'head.json')
    runs = []; seen = {str(root)}
    for head in dict.fromkeys(heads):
        head_pin = _source(_ordinary(head)); binding = json.loads(head.read_text())
        path = Path(binding['path']); path = _ordinary(path if path.is_absolute() else head.parent / path)
        state_pin = _source(path)
        if state_pin['sha256'] != binding['sha256'] or 'size' in binding and state_pin['size'] != binding['size']:
            raise ValueError('campaign state source changed')
        pins.extend([head_pin, state_pin]); campaign_roots.append(str(head.parent))
        from . import research_cycle as cycle
        _, state = cycle._load_history(head.parent)
        # The state population comes from replay; custody still binds original bytes.
        pins.extend(_source(_ordinary(head.parent / 'history' / f'{index:04d}.json'))
                    for index in range(state['revision'] + 1))
        if _source(head) != head_pin or _source(path) != state_pin:
            raise ValueError('campaign source changed during history replay')
        base = Path(state.get('base_dir', str(head.parent)))
        base = base if base.is_absolute() else head.parent / base
        for experiment in state.get('experiments', []):
            if experiment.get('rundir') is None: continue
            run = Path(experiment['rundir']); run = _ordinary(run if run.is_absolute() else base / run)
            if str(run) in seen: continue  # One actual run can appear in retained campaign revisions.
            seen.add(str(run)); runs.append(run)
    return runs, pins, campaign_roots


def build(rundir, *, status=None, _include_campaign=True):
    """Read-only seam for completion owners: build after the whole-parent gate."""
    from . import completion_disclosure, execution
    from .submission_export import code_version
    root = Path(rundir).absolute()
    if not root.is_dir(): raise ValueError('run directory required')
    ceiling = _byte_ceiling(root); procedure_status = _procedure_status(status)
    sources = []; nodes = []; ledger = execution.load_execution(root)
    if (root / execution.STATE_NAME).exists(): sources.append(_source(root / execution.STATE_NAME))
    stage_nodes = {}
    for stage, record in sorted(ledger['stages'].items()):
        # A merely planned stage is not falsely described as an executed node.
        if not record.get('attempt_id'): continue
        stage_nodes[stage] = 'stage:' + stage + ':' + str(record['attempt_id'])
    for stage, record in sorted(ledger['stages'].items()):
        if stage not in stage_nodes: continue
        bindings = _snapshot_pins(root, record.get('input_snapshot', {}), ceiling)
        try:
            bindings.update(_snapshot_pins(root, record.get('output_snapshot', {}), ceiling))
        except ValueError as exc:
            raise ValueError('recorded output changed: ' + str(exc)) from exc
        pins, missing = _files(root, [*record.get('inputs', []), *record.get('outputs', [])], bindings, ceiling)
        sources.extend(pins)
        nodes.append({'id': stage_nodes[stage], 'kind': 'stage', 'stage': stage, 'run': str(root),
                      'attempt_id': record['attempt_id'], 'status': record.get('status', 'unknown'),
                      'depends_on': [stage_nodes[p] for p in sorted(record.get('parents', {})) if p in stage_nodes],
                      'unresolved_parents': [p for p in sorted(record.get('parents', {})) if p not in stage_nodes],
                      'command': record.get('command'), 'source_pins': pins, 'missing_artifacts': missing})
    current_attempts = {(node['stage'], str(node['attempt_id'])) for node in nodes}
    for path in sorted(root.glob('logs/execution/*/*/record.json')):
        pin = _source(path); sources.append(pin); record = json.loads(path.read_text())
        identity = (record.get('stage', path.parent.parent.name), str(record['attempt_id']))
        if identity in current_attempts: continue
        nodes.append({'id': 'stage:' + identity[0] + ':' + identity[1], 'kind': 'historical-stage',
                      'stage': identity[0], 'attempt_id': identity[1], 'status': record.get('status', 'unknown'),
                      'depends_on': [], 'command': record.get('command'), 'source_pins': [pin], 'missing_artifacts': [],
                      'scope': 'Retained attempt record; historical artifact paths are not rebound to newer outputs.'})
    audit = worker_audit.build(root); sources.extend(audit['sources'])
    for i, session in enumerate(audit['sessions']):
        nodes.append({'id': 'worker:' + str(i), 'kind': 'worker', 'node_id': session['node_id'],
                      'attempt_id': session['attempt'], 'status': session['status'], 'depends_on': [],
                      'source_pins': [pin for pin in (session['receipt'], session['transcript']) if pin], 'missing_artifacts': []})
    disclosure = {'schema_version': 1, 'kind': 'research-disclosure-not-applicable',
        'reason': 'No recorded research protocol or research binding; no zero funnel or human-review claim inferred.'}
    if completion_disclosure.required(root):
        sources.extend(_source(p) for p in sorted((root / 'research').rglob('*.json')))
        try:
            disclosure = completion_disclosure.build(root)
            sources.extend(_disclosure_pins(disclosure, root, ceiling))
            sources.extend(_disclosure_pins(json.loads((root / 'research/protocol.json').read_text()), root, ceiling))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            if procedure_status == 'complete': raise
            disclosure = {'schema_version': 1, 'kind': 'research-disclosure-incomplete', 'reason': str(exc)}
    runtime = _runtime_snapshots(root)
    runtime_by_run = {str(root): runtime}
    sources.extend(_disclosure_pins(runtime, root, ceiling))
    profile = root / 'inputs/site-profile.json'
    if profile.exists(): sources.append(_source(_ordinary(profile)))
    run_dirs = [str(root)]; disclosures = []
    if _include_campaign:
        children, campaign_pins, campaign_roots = _campaign_runs(root); sources.extend(campaign_pins)
        run_dirs.extend(campaign_roots)
        worker_paths = {pin['path'] for node in nodes if node['kind'] == 'worker' for pin in node['source_pins']}
        for child in children:
            document = build(child, status=procedure_status, _include_campaign=False)
            prefix = 'run:' + str(child) + ':'
            for node in document['nodes']:
                if node['kind'] == 'worker':
                    paths = {pin['path'] for pin in node['source_pins']}
                    if paths and paths <= worker_paths: continue
                    worker_paths.update(paths)
                nodes.append({**node, 'id': prefix + node['id'], 'run': str(child),
                              'depends_on': [prefix + dep for dep in node['depends_on']]})
            sources.extend(document['source_pins']); run_dirs.extend(document['run_dirs'])
            disclosures.append({'run': str(child), 'disclosure': document['disclosure']})
            runtime_by_run[str(child)] = document['runtime_snapshots']
            known = {tuple(pin['path'] for pin in (row.get('receipt'), row.get('transcript')) if pin) for row in audit['sessions']}
            for row in document['workers']['sessions']:
                key = tuple(pin['path'] for pin in (row.get('receipt'), row.get('transcript')) if pin)
                if key not in known:
                    audit['sessions'].append(row); known.add(key)
            audit['gaps'].extend(gap for gap in document['workers']['gaps'] if gap not in audit['gaps'])
            audit['sources'].extend(pin for pin in document['workers']['sources'] if pin not in audit['sources'])
            audit['transcripts'] = sorted(set(audit['transcripts']) | set(document['workers']['transcripts']))
            audit['complete'] = not audit['gaps']
    unique = {}
    for pin in sources:
        prior = unique.get(pin['path'])
        if prior and prior['sha256'] is not None and pin['sha256'] is not None and (prior['sha256'], prior['size']) != (pin['sha256'], pin['size']):
            raise ValueError('conflicting procedure source bindings: ' + pin['path'])
        if prior is None or pin['sha256'] is not None: unique[pin['path']] = pin
    for pin in unique.values(): _check_pin(pin)
    env = env_snapshot.capture()
    return {'schema_version': 1, 'kind': 'ravel-procedure', 'run': str(root), 'code_version': code_version(),
            'nodes': nodes, 'workers': audit, 'environment': env, 'disclosure': disclosure,
            'campaign_disclosures': disclosures, 'runtime_snapshots': runtime, 'runtime_snapshots_by_run': runtime_by_run,
            'run_dirs': sorted(set(run_dirs)),
            'procedure_status': procedure_status, 'delivery_authorized': False,
            'byte_ceiling': ceiling, 'verification_scope': 'existence and size; recorded digests are bound without content verification',
            'source_pins': [unique[k] for k in sorted(unique)],
            'record_roster': sorted({p for run in run_dirs for p in _roster(Path(run))}), 'execution_authorized': False, 'physics_validated': False,
            'workflow_scope': 'Verify retained evidence one rule per recorded node; ordinary site-workflow is the governed recomputation route.',
            'limitations': [*(['Per-stage runtime snapshot interface unavailable; no historical environment inferred.']
                               if not callable(getattr(env_snapshot, 'runtime_snapshots', None)) else []),
                            'Model and token fields retain reported provenance; unknown values remain audit gaps.',
                            'Standalone exports retain absolute source pins and describe the original machine; original sources must remain available.',
                            'Scheduler profiles are configuration templates without native qualification.']}


def _roster(root):
    paths = [*root.glob('**/agent-work/*/*/receipt.json'), *root.glob('**/agent-work/*/*/transcript.jsonl'),
             *root.glob('research/**/*.json'), *root.glob('**/graph_state.json'), *root.glob('**/graph_spec.json'),
             *root.glob('**/calls/*.json'), *root.glob('logs/execution/*/*/record.json'), *root.glob('head.json'),
             *root.glob('execution_state.json'), *root.glob('inputs/completion_sources.json'),
             *root.glob('inputs/site-profile.json')]
    return sorted(str(p.absolute()) for p in paths)


def _note(document):
    lines = ['# Procedure note', '', document['workflow_scope'], '',
             'Export grants no execution authority or physics validation.', '',
             'Procedure status: ' + document['procedure_status'] + '.',
             'Refresh binds recorded digests and checks existence and size. Use verify --deep to check content.', '',
             '| Rule | Recorded node | Kind | Status | Dependencies |', '|---|---|---|---|---|']
    cell = lambda v: str(v).replace('|', '\\|').replace('\n', ' ')
    commands = []
    for i, node in enumerate(document['nodes']):
        lines.append(f"| node_{i} | {cell(node['id'])} | {node['kind']} | {cell(node['status'])} | {cell(', '.join(node['depends_on']))} |")
        if node.get('command'):
            commands.extend(['', 'Recorded command for ' + cell(node['id']) + ' (not dispatched by export):', '```json', json.dumps(node['command']), '```'])
    lines.extend(commands)
    lines.extend(['', '## Worker sessions', '', '| Role | Session | Model build | Timestamp | Input | Output | Graph | Version | Thread |',
                  '|---|---|---|---|---|---|---|---|---|'])
    for session in document['workers']['sessions']:
        graph = session.get('graph') or {}; tokens = session['tokens']
        fields = [session['role_id'], session['session_id'], session['model_build'], session['timestamp'],
                  tokens['input_tokens'], tokens['output_tokens'], graph.get('id'), graph.get('version'), graph.get('thread_id')]
        lines.append('| ' + ' | '.join(cell(v) if v is not None else 'unknown' for v in fields) + ' |')
    lines += ['', 'Audit gaps:', '```json', json.dumps(document['workers']['gaps'], indent=2), '```', '',
              '## Environment and code versions', '', '```json', json.dumps({'snapshot_id': document['environment']['snapshot_id'],
               'code': document['code_version']}, indent=2), '```', '', '## Computed disclosure', '',
              'The following block comes from the completion disclosure interface.', '```json',
              json.dumps(document['disclosure'], indent=2, sort_keys=True), '```', '', *document['limitations'], '']
    return '\n'.join(lines)


def snakefile(document, expected):
    ids = {n['id']: i for i, n in enumerate(document['nodes'])}
    lines = ['# Recorded procedure: evidence verification only; ordinary approvals remain required.',
             'rule all:', '    input: ' + repr([f'completed/node_{i}.json' for i in range(len(ids))])]
    # No top-level subprocess: a Snakemake dry-run never invokes RAVEL or native tools.
    for i, node in enumerate(document['nodes']):
        deps = [f'completed/node_{ids[d]}.json' for d in node['depends_on']]
        argv = ['ravel', 'procedure', 'verify-node', '--package', '.',
                '--node', str(i), '--expected-sha256', expected, '--out', f'completed/node_{i}.json']
        command = shlex.join(argv).replace('{', '{{').replace('}', '}}')
        lines += ['', f'rule node_{i}:', '    input: ' + repr(['procedure.json', 'closure.json', *deps]),
                  '    output: ' + repr(f'completed/node_{i}.json'), '    threads: 1', '    retries: 0', '    shell: ' + repr(command)]
    return '\n'.join(lines) + '\n'


def validate_snakefile(text, node_count):
    if text.count('\nrule node_') != node_count or text.count('    retries: 0') != node_count or 'rule all:' not in text:
        raise ValueError('procedure rule roster differs')
    if 'subprocess' in text or 'approve' in text or '--resume' in text:
        raise ValueError('procedure workflow cannot grant or dispatch scientific authority')
    return True


def theory_template():
    lines = ['# Theory chain template: fill canonical prepared site exports, not raw tool commands.',
             '# config: site_export, export_sha256, python, symbolic_task, numeric_task, fit_task',
             '# Execution still requires ordinary science approvals; this template has not run.']
    for stage, dep in [('symbolic', None), ('numeric', 'symbolic'), ('fit', 'numeric')]:
        lines += ['', f'rule {stage}:', '    input: ' + repr([] if dep is None else [dep + '.completed.json']),
                  '    output: ' + repr(stage + '.completed.json'), '    threads: 1', '    retries: 0',
                  '    params:', f'        task=config["{stage}_task"], manifest=config["site_export"], digest=config["export_sha256"], python=config["python"]',
                  '    shell:', '        "{params.python:q} -m ravel.workflow.site_workflow run-step --export {params.manifest:q} --task {params.task:q} --export-sha256 {params.digest:q} > {output:q}"']
    return '\n'.join(lines) + '\n'


def export(rundir, into, *, cores=1, baseline_environment=None, status=None, _document=None):
    from ravel.controller.sink import legacy as sink_legacy
    sink_legacy.refuse_controller_owned(rundir, 'procedure export')
    sink_legacy.refuse_controller_owned(Path(into).absolute().parent, 'procedure export')
    document = _document if _document is not None else build(rundir, status=status)
    out = Path(into).absolute()
    if out.exists(): raise ValueError('fresh procedure export directory required')
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.ravel-procedure-', dir=out.parent))
    try:
        _write(staging / 'procedure.json', document)
        expected = hashlib.sha256((staging / 'procedure.json').read_bytes()).hexdigest()
        (staging / 'procedure.md').write_text(_note(document))
        raw = snakefile(document, expected); validate_snakefile(raw, len(document['nodes']))
        (staging / 'Snakefile').write_text(raw)
        _write(staging / 'environment.json', document['environment'])
        before = json.loads(Path(baseline_environment).read_text()) if baseline_environment else document['environment']
        difference = env_snapshot.diff(before, document['environment'])
        difference['comparison_basis'] = 'supplied baseline' if baseline_environment else 'export-time snapshot compared with itself; no historical baseline supplied'
        _write(staging / 'environment-diff.json', difference)
        _write(staging / 'worker-audit.json', document['workers'])
        (staging / 'templates').mkdir(); (staging / 'templates/theory.smk').write_text(theory_template())
        (staging / 'templates/replay.smk').write_text(_replay_template())
        write_profiles(staging / 'profiles', cores=cores)
        files = [{'path': p.relative_to(staging).as_posix(), 'sha256': _source(p)['sha256'], 'size': p.stat().st_size}
                 for p in sorted(staging.rglob('*')) if p.is_file()]
        _write(staging / 'closure.json', {'schema_version': 1, 'files': files})
        verify(staging, expected_sha256=expected)
        staging.rename(out)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True); raise
    return {'directory': str(out), 'procedure_sha256': expected, 'nodes': len(document['nodes']),
            'procedure_status': document['procedure_status'], 'verification_scope': document['verification_scope'],
            'audit_complete': document['workers']['complete'], 'snapshot_id': document['environment']['snapshot_id'], 'execution_authorized': False}



def export_for_delivery(rundir, *, status=None):
    """Idempotent evidence export; refresh environment is observational, not identity."""
    from ravel.controller.sink import legacy as sink_legacy
    sink_legacy.refuse_controller_owned(rundir, 'procedure export')
    document = build(rundir, status=status)
    identity_keys = ('source_pins', 'record_roster', 'nodes', 'disclosure', 'campaign_disclosures',
                     'runtime_snapshots_by_run', 'procedure_status', 'byte_ceiling')
    identity = hashlib.sha256(_encoded({key: document[key] for key in identity_keys})).hexdigest()
    out = Path(rundir).absolute() / 'procedure-exports' / identity
    if out.exists():
        retained = verify(out)
        if any(retained[key] != document[key] for key in identity_keys):
            raise ValueError('retained procedure differs from current recorded run')
        return {'directory': str(out), 'reused': True, 'snapshot_id': retained['environment']['snapshot_id'],
                'procedure_status': retained['procedure_status'], 'verification_scope': retained['verification_scope'],
                'execution_authorized': False}
    profile = Path(rundir) / 'inputs/site-profile.json'
    cores = json.loads(profile.read_text())['cores'] if profile.exists() else 1
    return {**export(rundir, out, cores=cores, _document=document), 'reused': False}


def attach_to_report(completion_pin, *, base_dir):
    """One-call seam after require_final; do not change the completion gate."""
    path = Path(completion_pin['path']); path = path if path.is_absolute() else Path(base_dir) / path
    if _source(path)['sha256'] != completion_pin['sha256']:
        raise ValueError('task completion changed before procedure export')
    request = json.loads(path.read_text()); parent = request.get('parent_review')
    if type(parent) is not dict or type(parent.get('rundir')) is not str:
        raise ValueError('actual closed parent review root required')
    root = Path(parent['rundir']); root = root if root.is_absolute() else Path(base_dir) / root
    return export_for_delivery(root)


def verify(package, *, deep=False, expected_sha256=None):
    root = _ordinary(package); path = root / 'procedure.json'
    if expected_sha256 is not None and _source(path)['sha256'] != expected_sha256:
        raise ValueError('procedure manifest changed')
    closure = json.loads((root / 'closure.json').read_text())
    members = set()
    for pin in closure['files']:
        relative = Path(pin['path'])
        if relative.is_absolute() or '..' in relative.parts: raise ValueError('procedure closure path escaped')
        if relative.as_posix() in members: raise ValueError('duplicate procedure member')
        members.add(relative.as_posix()); actual = _source(root / relative)
        if actual['sha256'] != pin['sha256'] or actual['size'] != pin['size']:
            raise ValueError('procedure member changed: ' + pin['path'])
    actual_members = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and not p.relative_to(root).as_posix().startswith(('completed/', '.snakemake/'))}
    if actual_members != members | {'closure.json'}: raise ValueError('procedure member roster changed')
    document = json.loads(path.read_text())
    embedded = document.get('path_basis') == 'package-relative'
    if embedded:
        references = [pin['path'] for pin in document['source_pins']] + document.get('run_dirs', [document['run']])
        references += [pin['path'] for node in document['nodes'] for pin in node['source_pins']]
        for value in references:
            relative = Path(value)
            if relative.is_absolute() or not (root / relative).resolve().is_relative_to(root.parent.resolve()):
                raise ValueError('embedded procedure reference escaped package')
    for pin in document['source_pins']:
        _check_pin(pin, deep=deep, base=root)
    roster = sorted({p for run in document.get('run_dirs', [document['run']])
                     for p in _roster(Path(run) if Path(run).is_absolute() else root / run)})
    if document.get('path_basis') == 'package-relative':
        roster = sorted(Path(os.path.relpath(p, root)).as_posix() for p in roster)
    if roster != document['record_roster']: raise ValueError('worker/research record roster changed')
    env_snapshot.diff(document['environment'], document['environment'])
    validate_snakefile((root / 'Snakefile').read_text(), len(document['nodes']))
    return document


def verify_node(package, node, expected_sha256, output):
    document = verify(package, expected_sha256=expected_sha256)
    if not 0 <= node < len(document['nodes']): raise ValueError('unknown procedure node')
    record = document['nodes'][node]
    node_paths = {pin['path'] for row in document['nodes'] for pin in row['source_pins']}
    shared = [pin for pin in document['source_pins'] if pin['path'] not in node_paths]
    for pin in [*shared, *record['source_pins']]: _check_pin(pin, deep=True, base=Path(package))
    if record['missing_artifacts'] or record.get('unresolved_parents'):
        raise ValueError('recorded node has unresolved evidence')
    out = Path(output)
    expected = (Path(package) / f'completed/node_{node}.json').absolute()
    if out.absolute() != expected: raise ValueError('canonical verification marker required')
    out.parent.mkdir(exist_ok=True)
    with out.open('x') as stream:
        stream.write(_encoded({'node': record['id'], 'recorded_status': record['status'],
                              'procedure_sha256': expected_sha256, 'evidence_unchanged': True, 'physics_validated': False}).decode())
    return {'node': record['id'], 'evidence_unchanged': True, 'physics_validated': False}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel procedure', description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    exp = commands.add_parser('export'); exp.add_argument('--rundir', type=Path, required=True)
    exp.add_argument('--into', type=Path, required=True); exp.add_argument('--cores', type=int, default=1)
    exp.add_argument('--baseline-environment', type=Path)
    ver = commands.add_parser('verify'); ver.add_argument('--package', type=Path, required=True)
    ver.add_argument('--deep', action='store_true', help='hash every bound source; default checks existence and size')
    node = commands.add_parser('verify-node'); node.add_argument('--package', type=Path, required=True)
    node.add_argument('--node', type=int, required=True); node.add_argument('--expected-sha256', required=True); node.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'export': result = export(args.rundir, args.into, cores=args.cores, baseline_environment=args.baseline_environment)
        elif args.command == 'verify-node': result = verify_node(args.package, args.node, args.expected_sha256, args.out)
        else:
            document = verify(args.package, deep=args.deep); result = {'passed': True, 'nodes': len(document['nodes']),
                'deep': args.deep, 'verification_scope': 'content digests' if args.deep else document.get('verification_scope', 'existence and size'),
                'physics_validated': False}
        print(json.dumps(result, indent=2, sort_keys=True)); return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f'procedure export: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
