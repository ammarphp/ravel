"""Export an accepted RAVEL analysis as a relocatable submission package.

The package is a directory of relative paths that can be committed to any
repository: the analysis recipe and code, the code version, an environment lock,
the workflow graph, input references with checksums, the accepted results, the
figures, the note, the run's decision records and the agent session audit log.
``submission.json`` lists every file with its sha256. ``verify`` re-checks a
package where it stands, and ``--fresh-clone`` repeats the check in a fresh git
clone (or a fresh copy outside git) so that files a repository would drop are
found before submission.

Every exported result must be captured by an accepted RAVEL review of the named
claim scope. Large inputs are referenced, never copied. Venue rules (required
parts, file size ceilings, note formats) are supplied as a rule-pack file.

  ravel export-submission --request REQUEST.json --into REPO [--subdir NAME] [--rules RULES.json]
  ravel export-submission verify --package DIR [--fresh-clone]
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

SCHEMA_VERSION = 1
MANIFEST = 'submission.json'
REQUEST_KIND = 'ravel-submission-request'
RULES_KIND = 'submission-rules'
REQUEST_KEYS = ('schema_version', 'kind', 'title', 'rundir', 'claim_scope', 'results', 'figures', 'note', 'recipe',
                'code', 'environment', 'inputs', 'audit', 'partitions', 'site_workflow', 'code_repository')
COPIED = ('results', 'figures', 'note', 'recipe', 'code', 'environment')
CATEGORIES = (*COPIED, 'run', 'audit', 'workflow', 'partitions', 'inputs', 'reproduce')
RUN_RECORD_MAX_BYTES = 8 * 1024 ** 2
SKIPPED_SUFFIXES = ('.lock',)
GENERATED = (MANIFEST,)
WORK_DIRS = ('.reproduce/', '.snakemake/')
SNAKEFILE = '''# Submission workflow. Every path is relative to this directory.
import json

FILES = [row["path"] for row in json.load(open("submission.json"))["files"]]


rule all:
    input: ".reproduce/verified.json"


rule verify:
    input: ["submission.json"] + FILES
    output: ".reproduce/verified.json"
    shell: "ravel export-submission verify --package . > {output}"
'''


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def _hex64(value):
    return type(value) is str and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _text(value):
    return type(value) is str and bool(value.strip())


def _paths(value, label):
    if type(value) is not list or any(not _text(v) for v in value):
        raise ValueError(f'{label} is a list of paths')
    return value


# ---------------------------------------------------------------- request and rules

def validate_request(request):
    if type(request) is not dict or set(request) != set(REQUEST_KEYS):
        raise ValueError('submission request requires exactly ' + ', '.join(REQUEST_KEYS))
    if request['schema_version'] != 1 or request['kind'] != REQUEST_KIND:
        raise ValueError(f'{REQUEST_KIND}/v1 request required')
    for key in ('title', 'rundir', 'claim_scope'):
        if not _text(request[key]):
            raise ValueError(f'{key} is required')
    for key in COPIED:
        _paths(request[key], key)
    if not request['results']:
        raise ValueError('name at least one accepted result')
    if type(request['inputs']) is not list:
        raise ValueError('inputs is a list of references')
    for row in request['inputs']:
        if type(row) is not dict or not _text(row.get('name')) or (('path' in row) == ('uri' in row)):
            raise ValueError('each input has a name and exactly one of path or uri')
        if set(row) - {'name', 'path', 'uri', 'sha256', 'size', 'description'}:
            raise ValueError('unknown input reference field')
        if 'uri' in row and not _hex64(row.get('sha256')):
            raise ValueError(f"remote input {row['name']!r} needs its sha256; checksums are never assumed")
        if 'sha256' in row and not _hex64(row['sha256']):
            raise ValueError(f"input {row['name']!r} sha256 must be 64 lowercase hex digits")
    audit = request['audit']
    if type(audit) is not dict or set(audit) != {'logs', 'transcripts'}:
        raise ValueError('audit requires logs and transcripts lists')
    _paths(audit['logs'], 'audit.logs')
    _paths(audit['transcripts'], 'audit.transcripts')
    _paths(request['partitions'], 'partitions')
    site = request['site_workflow']
    if site is not None and (type(site) is not dict or set(site) != {'export', 'sha256'}
                             or not _text(site['export']) or not _hex64(site['sha256'])):
        raise ValueError('site_workflow is null or {export, sha256}')
    repo = request['code_repository']
    if repo is not None and (type(repo) is not dict or set(repo) != {'url', 'commit'}
                             or not all(_text(v) for v in repo.values())):
        raise ValueError('code_repository is null or {url, commit}')
    return request


def validate_rules(rules):
    keys = {'schema_version', 'kind', 'required', 'note_suffixes', 'max_file_bytes', 'max_total_bytes'}
    if type(rules) is not dict or set(rules) != keys:
        raise ValueError('submission rules require exactly ' + ', '.join(sorted(keys)))
    if rules['schema_version'] != 1 or rules['kind'] != RULES_KIND:
        raise ValueError(f'{RULES_KIND}/v1 rules required')
    if type(rules['required']) is not list or any(r not in CATEGORIES for r in rules['required']):
        raise ValueError('required parts are drawn from ' + ', '.join(CATEGORIES))
    if type(rules['note_suffixes']) is not list or any(not _text(s) or not s.startswith('.') for s in rules['note_suffixes']):
        raise ValueError('note_suffixes is a list such as [".pdf"]')
    for key in ('max_file_bytes', 'max_total_bytes'):
        if rules[key] is not None and (type(rules[key]) is not int or rules[key] <= 0):
            raise ValueError(f'{key} is a positive integer or null')
    return rules


def rule_errors(manifest, rules):
    errors = []
    present = {row['category'] for row in manifest['files']}
    if manifest['inputs']:
        present.add('inputs')
    for part in rules['required']:
        if part not in present:
            errors.append(f'the rules require {part} and the package has none')
    if rules['note_suffixes']:
        for row in manifest['files']:
            if row['category'] == 'note' and Path(row['path']).suffix.lower() not in [s.lower() for s in rules['note_suffixes']]:
                errors.append(f"{row['path']} is not one of the allowed note formats " + ', '.join(rules['note_suffixes']))
    if rules['max_file_bytes'] is not None:
        for row in manifest['files']:
            if row['size'] > rules['max_file_bytes']:
                errors.append(f"{row['path']} is larger than {rules['max_file_bytes']} bytes")
    total = sum(row['size'] for row in manifest['files'])
    if rules['max_total_bytes'] is not None and total > rules['max_total_bytes']:
        errors.append(f"the package holds {total} bytes, larger than {rules['max_total_bytes']}")
    return errors


# ---------------------------------------------------------------- building blocks

class _Package:
    def __init__(self, root, base):
        self.root, self.base, self.files = Path(root), Path(base), []

    def resolve(self, value):
        path = Path(value).expanduser()
        return (path if path.is_absolute() else self.base / path).absolute()

    def origin(self, path):
        try:
            return str(Path(path).relative_to(self.base))
        except ValueError:
            return Path(path).name

    def copy(self, source, relative, category):
        source = Path(source)
        if source.is_symlink() or not source.is_file():
            raise ValueError(f'{source} is not a regular file')
        target = self.root / relative
        if target.exists():
            raise ValueError(f'two exported files share the package path {relative}')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return self.add(relative, category, origin=self.origin(source))

    def write(self, relative, text, category):
        target = self.root / relative
        if target.exists():
            raise ValueError(f'two exported files share the package path {relative}')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            stream.write(text)
        return self.add(relative, category)

    def write_json(self, relative, value, category):
        return self.write(relative, json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', category)

    def add(self, relative, category, origin=None):
        path = self.root / relative
        row = {'path': Path(relative).as_posix(), 'category': category, 'sha256': file_sha256(path),
               'size': path.stat().st_size}
        if origin is not None:
            row['origin'] = origin
        self.files.append(row)
        return row


def _results(pkg, request, rundir):
    from .result_templates import accepted
    acceptance = None
    for value in request['results']:
        path = pkg.resolve(value)
        try:
            _, _, record = accepted(path, rundir=rundir, claim_scope=request['claim_scope'], base_dir=path.parent)
        except (ValueError, KeyError, OSError) as exc:
            raise ValueError(f'{path.name} is not captured by an accepted review of '
                             f"{request['claim_scope']!r}: {exc}") from exc
        if acceptance is not None and record['review_sequence'] != acceptance['review_sequence']:
            raise ValueError('every exported result must come from the same accepted review')
        acceptance = record
        pkg.copy(path, f'results/{path.name}', 'results')
    return {'accepted': True, 'claim_scope': request['claim_scope'], 'review_sequence': acceptance['review_sequence'],
            'run': Path(rundir).name}


def _run_records(rundir):
    rundir = Path(rundir)
    selected = [p for p in rundir.iterdir() if p.is_file() and not p.is_symlink()]
    for folder, pattern in (('inputs', '**/*'), ('logs/physics_review', '**/*'), ('logs/execution', '**/record.json')):
        if (rundir / folder).is_dir():
            selected += [p for p in (rundir / folder).glob(pattern) if p.is_file() and not p.is_symlink()]
    return sorted({p for p in selected if not p.name.endswith(SKIPPED_SUFFIXES)})


def _copy_run(pkg, rundir, references):
    for path in _run_records(rundir):
        relative = path.relative_to(rundir).as_posix()
        if path.stat().st_size > RUN_RECORD_MAX_BYTES:
            references.append({'name': f'run file {relative}', 'reference': 'local', 'origin': f'run/{relative}',
                               'sha256': file_sha256(path), 'size': path.stat().st_size})
            continue
        pkg.copy(path, f'run/{relative}', 'run')


def _inputs(pkg, request):
    rows = []
    for row in request['inputs']:
        out = {'name': row['name']}
        if 'description' in row:
            out['description'] = row['description']
        if 'uri' in row:
            out.update(reference='remote', uri=row['uri'], sha256=row['sha256'], size=row.get('size'))
        else:
            path = pkg.resolve(row['path'])
            if not path.is_file():
                raise ValueError(f"input {row['name']!r} is not a readable file: {path.name}")
            digest = file_sha256(path)
            if 'sha256' in row and row['sha256'] != digest:
                raise ValueError(f"input {row['name']!r} differs from its declared sha256")
            out.update(reference='local', origin=pkg.origin(path), sha256=digest, size=path.stat().st_size)
        rows.append(out)
    return rows


def _git(*args, cwd=None):
    git = '/usr/bin/git' if Path('/usr/bin/git').exists() else shutil.which('git')
    if git is None:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    done = subprocess.run([git, *args], cwd=cwd, capture_output=True, text=True, env=env, timeout=120)
    return done


def code_version(repository=None):
    from ravel import __version__
    source = Path(__file__).resolve().parents[1]
    value = {'ravel_version': __version__, 'source_commit': None, 'source_modified': None,
             'analysis_repository': repository}
    head = _git('rev-parse', 'HEAD', cwd=source)
    if head is not None and head.returncode == 0:
        value['source_commit'] = head.stdout.strip()
        status = _git('status', '--porcelain', '--', '.', cwd=source)
        value['source_modified'] = bool(status.stdout.strip()) if status is not None and status.returncode == 0 else None
    return value


def environment_lock(rundir, package_dir):
    """Export recorded stage environments; never snapshot the exporter."""
    from . import env_snapshot, environment_export
    return environment_export.write(package_dir, env_snapshot.runtime_snapshots(rundir))


def _plan_stages(rundir):
    stages = {}
    for relative in ('inputs/science-plan.json', 'inputs/native_execution_plan.json'):
        path = Path(rundir) / relative
        if not path.is_file():
            continue
        plan = json.loads(path.read_text())
        for stage in plan.get('stages', []) if type(plan) is dict else []:
            if type(stage) is dict and _text(stage.get('stage')):
                stages[stage['stage']] = {'plan': relative, 'inputs': list(stage.get('inputs', [])),
                                          'outputs': list(stage.get('outputs', [])),
                                          'depends_on': list(stage.get('depends_on', []))}
    return stages


def _run_path(value, rundir):
    """A stage path as the package sees it: run/<path> inside the run, external:<name> outside."""
    path = Path(str(value))
    if not path.is_absolute():
        return 'run/' + path.as_posix()
    try:
        return 'run/' + path.resolve().relative_to(Path(rundir).resolve()).as_posix()
    except ValueError:
        return 'external:' + path.name


def workflow_graph(rundir, partitions, site):
    from .execution import load_execution
    planned = _plan_stages(rundir)
    ledger = load_execution(rundir)['stages']
    nodes, edges = [], []
    for name in sorted(set(planned) | set(ledger)):
        plan, record = planned.get(name, {}), ledger.get(name, {})
        depends = sorted(set(plan.get('depends_on', [])) | set((record.get('parents') or {}).keys()))
        nodes.append({'id': f'stage:{name}', 'kind': 'stage', 'planned': name in planned,
                      'status': record.get('status', 'planned'), 'attempt_id': record.get('attempt_id'),
                      'inputs': [_run_path(v, rundir) for v in (record.get('inputs') or plan.get('inputs', []))],
                      'outputs': [_run_path(v, rundir) for v in (record.get('outputs') or plan.get('outputs', []))]})
        edges += [{'from': f'stage:{d}', 'to': f'stage:{name}'} for d in depends]
    nodes += partitions
    if site is not None:
        nodes.append(site)
    return {'schema_version': 1, 'kind': 'ravel-workflow-graph', 'run': Path(rundir).name, 'nodes': nodes,
            'edges': edges}


def _partitions(pkg, works):
    if not works:
        return []
    from importlib import import_module
    try:
        partitioned = import_module('ravel.workflow.partitioned_execution')
    except ImportError as exc:
        raise ValueError('partitioned execution is not available in this RAVEL installation') from exc
    nodes = []
    for value in works:
        work = pkg.resolve(value)
        status = partitioned.summary(work)
        if status['status'] != 'complete':
            raise ValueError(f"partitioned run {status['name']!r} is incomplete; failed or pending: "
                             + ', '.join(status['failed'] + status['pending']))
        receipt_path = work / partitioned.MERGE_RECEIPT
        if not receipt_path.is_file():
            raise ValueError(f"partitioned run {status['name']!r} has no merge receipt; merge it first")
        receipt = json.loads(receipt_path.read_text())
        folder = f"partitions/{status['name']}"
        pkg.copy(receipt_path, f'{folder}/{receipt_path.name}', 'partitions')
        outputs = []
        for row in receipt['merged']:
            if row.get('merge') == 'none':
                continue
            source = Path(row['path'])
            if file_sha256(source) != row['sha256']:
                raise ValueError(f"merged output {row['name']} differs from its merge receipt")
            outputs.append(pkg.copy(source, f"{folder}/{row['name']}", 'partitions')['path'])
        nodes.append({'id': f"partitions:{status['name']}", 'kind': 'partitioned-stage', 'status': 'complete',
                      'partitions': status['partitions'], 'specification_sha256': receipt.get('specification_sha256'),
                      'outputs': outputs})
    return nodes


def _site(pkg, site):
    if site is None:
        return None
    from . import site_workflow
    export = pkg.resolve(site['export'])
    document = site_workflow.verify(export / 'workflow.json', site['sha256'])
    copied = [pkg.copy(export / name, f'workflow/site/{name}', 'workflow')['path']
              for name in ('workflow.json', 'Snakefile', 'export-closure.json')]
    return {'id': 'site-workflow', 'kind': 'site-workflow', 'status': 'verified at export',
            'tasks': [t.get('id') for t in (document or {}).get('tasks', [])], 'files': copied,
            'note': 'The site workflow names paths on the machine that ran it.'}


def _audit(pkg, audit, rundir=None):
    from . import agent_audit
    logs = [pkg.resolve(v) for v in audit['logs']]
    transcripts = [pkg.resolve(v) for v in audit['transcripts']]
    from .worker_audit import build as worker_records
    workers = worker_records(rundir) if rundir is not None else None
    if workers is not None:
        transcripts = list(dict.fromkeys([*transcripts, *(Path(p) for p in workers['transcripts'])]))
    if not logs and not transcripts and workers is None:
        return None
    written = []
    if logs:
        for i, log in enumerate(logs):
            folder = 'audit' if len(logs) == 1 else f'audit/log-{i + 1}'
            written.append(agent_audit.build(log, transcripts if i == 0 else (), pkg.root / folder))
    else:
        written.append(agent_audit.write(agent_audit.collect(transcripts), pkg.root / 'audit'))
    for result in written:
        for path in result['files']:
            pkg.add(Path(path['path'] if type(path) is dict else path).relative_to(pkg.root), 'audit')
    for i, log in enumerate(logs):
        pkg.copy(log, 'audit/hook-log.jsonl' if len(logs) == 1 else f'audit/log-{i + 1}/hook-log.jsonl', 'audit')
    if workers is not None:
        pkg.write_json('audit/worker-audit.json', workers, 'audit')
        for i, session in enumerate(workers['sessions']):
            for key in ('receipt', 'transcript'):
                if session.get(key):
                    pkg.copy(session[key]['path'], f'audit/workers/{i}/{key}' + ('.jsonl' if key == 'transcript' else '.json'), 'audit')
    return {'prompts': sum(r.get('prompts', 0) for r in written),
            'workers_complete': workers['complete'] if workers is not None else None}


def _reproduce(manifest):
    code = manifest['code_version']
    lines = [f"# {manifest['title']}", '',
             'This directory is a self-contained RAVEL submission package. Every file is listed with its sha256 in',
             '`submission.json`; every path is relative to this directory.', '',
             '## Check the package', '',
             '```', 'ravel export-submission verify --package .', '```', '',
             '`snakemake -n` in this directory resolves every packaged file; `snakemake --cores 1` runs the same check.', '',
             '## Recreate the environment', '',
             f"RAVEL {code['ravel_version']}" + (f" at source commit `{code['source_commit']}`" if code['source_commit'] else '') + '.',
             'Recorded stage environments are under `environment/runtime/`. Their package union is in',
             '`environment/analysis-requirements.txt`; RAVEL is pinned separately in `environment/ravel-requirements.txt`.',
             'The hash-locked WMS dependencies are in `environment/wms-requirements.lock`.',
             'Use the Python version and operating system recorded by the executing stages; native tool versions,',
             'facility views and container identities are provenance, and require separately provisioned runtimes.',
             'The setup script creates `.venv-analysis` and `.venv-wms` and links `ravel` and `snakemake` into `.bin/`.',
             'Each environment installs its own pins so their conflicting packaging versions stay isolated.',
             'It requires the separate RAVEL pin, and runs only when explicitly invoked:', '',
             '```', 'sh environment/setup.sh', 'export PATH="$PWD/.bin:$PATH"', '```', '',
             '## Fetch the inputs', '',
             'Inputs are referenced in `inputs.json`, each with its sha256. Fetch each one and compare its checksum',
             'before rerunning the analysis.', '',
             '## Rerun', '',
             'The workflow graph is in `workflow/dag.json`; the run plan, approvals and review records are under `run/`.',
             'Recreate the run from `run/inputs/` with the RAVEL lifecycle (plan, approve, run) and compare the new',
             'results with `results/`.', '']
    return '\n'.join(lines)


# ---------------------------------------------------------------- export

def export(request_path, into, *, subdir='submission', rules=None):
    """Write a submission package into `into/subdir`; return its summary."""
    request_path = Path(request_path).absolute()
    request = validate_request(json.loads(request_path.read_text()))
    rules_value = validate_rules(json.loads(Path(rules).read_text())) if rules is not None else None
    if not _text(subdir) or Path(subdir).is_absolute() or '..' in Path(subdir).parts:
        raise ValueError('subdir is a relative directory name inside the repository')
    root = (Path(into).absolute() / subdir)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise ValueError(f'{root} must be new or empty; an existing package is never overwritten')
    staging = Path(tempfile.mkdtemp(prefix='.ravel-submission-', dir=_existing_parent(root)))
    try:
        pkg = _Package(staging, request_path.parent)
        rundir = pkg.resolve(request['rundir'])
        if not rundir.is_dir():
            raise ValueError('rundir is not a directory')
        from . import gate_wiring  # R3: a delegated epoch-two run exports only under the export gate
        gate_wiring.require_delegated(rundir, 'export', gate_wiring.export_action(rundir, request_path))
        acceptance = _results(pkg, request, rundir)
        for category in ('figures', 'note', 'recipe', 'code', 'environment'):
            for value in request[category]:
                path = pkg.resolve(value)
                pkg.copy(path, f'{category}/{path.name}', category)
        references = _inputs(pkg, request)
        _copy_run(pkg, rundir, references)
        pkg.write_json('inputs.json', {'schema_version': 1, 'kind': 'ravel-input-references', 'inputs': references},
                       'inputs')
        for pin in environment_lock(rundir, pkg.root):
            pkg.add(pin['path'], 'environment')
        partitions = _partitions(pkg, request['partitions'])
        site = _site(pkg, request['site_workflow'])
        pkg.write_json('workflow/dag.json', workflow_graph(rundir, partitions, site), 'workflow')
        audit = _audit(pkg, request['audit'], rundir)
        from .procedure_export import export as export_procedure
        export_procedure(rundir, pkg.root / 'procedure')
        for path in sorted((pkg.root / 'procedure').rglob('*')):
            if path.is_file(): pkg.add(path.relative_to(pkg.root), 'workflow')
        manifest = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-submission', 'title': request['title'],
                    'created_utc': utc_now(), 'acceptance': acceptance,
                    'code_version': code_version(request['code_repository']),
                    'inputs': references, 'audit': audit, 'files': [],
                    'machine_approval_is_not_human_review': True}
        manifest['files'] = pkg.files
        pkg.write('REPRODUCE.md', _reproduce(manifest), 'reproduce')
        pkg.write('Snakefile', SNAKEFILE, 'reproduce')
        manifest['files'] = sorted(pkg.files, key=lambda r: r['path'])
        if rules_value is not None:
            manifest['rules'] = {'sha256': file_sha256(rules), 'origin': Path(rules).name}
            errors = rule_errors(manifest, rules_value)
            if errors:
                raise ValueError('; '.join(errors))
        with (staging / MANIFEST).open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n')
        if root.exists():
            root.rmdir()
        root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(root)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    report = verify(root)
    if not report['passed']:
        raise ValueError('the written package failed its own check: ' + '; '.join(report['errors']))
    return {'package': str(root), 'manifest_sha256': file_sha256(root / MANIFEST), 'files': len(manifest['files']),
            'acceptance': acceptance, 'warnings': report['warnings']}


def _existing_parent(path):
    for parent in Path(path).parents:
        if parent.is_dir():
            return parent
    raise ValueError('no existing parent directory')


# ---------------------------------------------------------------- verification

def _check(package):
    package = Path(package).absolute()
    errors, warnings = [], []
    manifest_path = package / MANIFEST
    if not manifest_path.is_file():
        return {'passed': False, 'errors': [f'{MANIFEST} is missing'], 'warnings': [], 'files': 0}
    manifest = json.loads(manifest_path.read_text())
    listed = set()
    for row in manifest.get('files', []):
        relative = Path(row['path'])
        if relative.is_absolute() or '..' in relative.parts:
            errors.append(f"{row['path']} is not a relative path inside the package")
            continue
        listed.add(relative.as_posix())
        path = package / relative
        if path.is_symlink() or not path.is_file():
            errors.append(f"{row['path']} is missing")
        elif file_sha256(path) != row['sha256']:
            errors.append(f"{row['path']} differs from its recorded sha256")
    for path in package.rglob('*'):
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(package).as_posix()
            if relative not in listed and relative not in GENERATED and not relative.startswith(WORK_DIRS):
                errors.append(f'{relative} is in the package but not listed in {MANIFEST}')
    own = str(package)
    for row in manifest.get('files', []):
        path = package / row['path']
        if path.is_file() and row['size'] <= RUN_RECORD_MAX_BYTES:
            try:
                if own in path.read_text(encoding='utf-8'):
                    errors.append(f"{row['path']} names the package's own absolute location")
            except UnicodeDecodeError:
                pass
    for row in manifest.get('inputs', []):
        if not _hex64(row.get('sha256')):
            errors.append(f"input {row.get('name')!r} has no sha256")
    if manifest.get('acceptance', {}).get('accepted') is not True:
        errors.append('the package does not record an accepted review')
    if (package / 'workflow/dag.json').is_file():
        dag = json.loads((package / 'workflow/dag.json').read_text())
        for node in dag['nodes']:
            for output in node.get('outputs', []) if node.get('kind') == 'partitioned-stage' else []:
                if output not in listed:
                    errors.append(f"workflow output {output} is not in the package")
    return {'passed': not errors, 'errors': errors, 'warnings': warnings, 'files': len(listed)}


def snakemake_dry_run(package):
    """Run `snakemake -n` in the package; every rule input must resolve."""
    if not (Path(package) / 'Snakefile').is_file():
        return {'status': 'failed', 'detail': 'Snakefile is missing'}
    from .wms_runtime import snakemake_argv
    argv = snakemake_argv()
    if not argv:
        return {'status': 'not-installed', 'detail': 'snakemake not found (RAVEL_SNAKEMAKE, site record or PATH)'}
    done = subprocess.run([*argv, '-n', '--cores', '1', '--snakefile', 'Snakefile'], cwd=package,
                          capture_output=True, text=True, timeout=300)
    detail = (done.stdout + done.stderr).strip()[-2000:]
    return {'status': 'passed' if done.returncode == 0 else 'failed', 'detail': detail}


def verify(package, *, fresh_clone=False):
    """Check a package; with fresh_clone, check it again in a fresh clone or copy."""
    package = Path(package).absolute()
    report = _check(package)
    if not fresh_clone:
        return report
    top = _git('rev-parse', '--show-toplevel', cwd=package) if package.is_dir() else None
    with tempfile.TemporaryDirectory(prefix='ravel-fresh-') as scratch:
        if top is not None and top.returncode == 0:
            top_dir = Path(top.stdout.strip()).resolve()
            relative = package.resolve().relative_to(top_dir)
            status = _git('status', '--porcelain', '--untracked-files=all', '--', str(relative), cwd=top_dir)
            if status.stdout.strip():
                report['errors'].append('the package has uncommitted changes; commit it before the fresh-clone check')
                report['passed'] = False
                report['fresh_clone'] = {'method': 'git clone', 'checked': False}
                return report
            target = Path(scratch) / 'clone'
            done = _git('clone', '--quiet', '--no-hardlinks', str(top_dir), str(target))
            if done is None or done.returncode != 0:
                raise ValueError('git clone failed: ' + (done.stderr.strip() if done else 'git not found'))
            fresh = target / relative
            method = 'git clone'
        else:
            fresh = Path(scratch) / package.name
            shutil.copytree(package, fresh, symlinks=True)
            method = 'copy'
        second = _check(fresh)
        dry_run = snakemake_dry_run(fresh)
    report['fresh_clone'] = {'method': method, 'checked': True, 'passed': second['passed'], 'snakemake': dry_run}
    if dry_run['status'] == 'failed':
        second['errors'].append('snakemake dry run failed: ' + dry_run['detail'])
    elif dry_run['status'] == 'not-installed':
        report['warnings'].append('snakemake is not installed here; the workflow dry run was not performed')
    report['errors'] += [f'fresh {method}: {e}' for e in second['errors']]
    report['passed'] = not report['errors']
    return report


# ---------------------------------------------------------------- command line

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ['verify']:
        parser = argparse.ArgumentParser(prog='ravel export-submission verify', description='check a submission package')
        parser.add_argument('--package', type=Path, required=True)
        parser.add_argument('--fresh-clone', action='store_true', help='repeat the check in a fresh git clone or copy')
        args = parser.parse_args(argv[1:])
        try:
            report = verify(args.package, fresh_clone=args.fresh_clone)
        except (OSError, ValueError, KeyError) as exc:
            parser.exit(1, f'export submission: {exc}\n')
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    parser = argparse.ArgumentParser(prog='ravel export-submission', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--request', type=Path, required=True, help='submission request JSON')
    parser.add_argument('--into', type=Path, required=True, help='repository or directory to write into')
    parser.add_argument('--subdir', default='submission', help='package directory inside --into')
    parser.add_argument('--rules', type=Path, help='venue rule pack JSON')
    args = parser.parse_args(argv)
    try:
        result = export(args.request, args.into, subdir=args.subdir, rules=args.rules)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'export submission: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
