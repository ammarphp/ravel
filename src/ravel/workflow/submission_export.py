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
import ast
from runpy import run_path
import fnmatch
import gzip
import io
import re
import tarfile
import tomllib
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
WORK_DIRS = ('.git/', '.reproduce/', '.snakemake/', 'procedure/completed/', '.venv-analysis/', '.venv-wms/')
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


def _copy_run(pkg, rundir, references, *, prefix='run'):
    for path in _run_records(rundir):
        relative = path.relative_to(rundir).as_posix()
        if path.stat().st_size > RUN_RECORD_MAX_BYTES:
            references.append({'name': f'run file {relative}', 'reference': 'local', 'origin': f'{prefix}/{relative}',
                               'sha256': file_sha256(path), 'size': path.stat().st_size})
            continue
        pkg.copy(path, f'{prefix}/{relative}', 'run')


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


def _git(*args, cwd=None, text=True):
    git = '/usr/bin/git' if Path('/usr/bin/git').exists() else shutil.which('git')
    if git is None:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    done = subprocess.run([git, *args], cwd=cwd, capture_output=True, text=text, env=env, timeout=120)
    return done


def _package_metadata():
    project_file = Path(__file__).resolve().parents[3] / 'pyproject.toml'
    if project_file.is_file():
        project = tomllib.loads(project_file.read_text())['project']
        name, version = project['name'], str(project['version'])
    else:
        from importlib.metadata import distribution
        metadata = distribution('ravel-hep')
        name, version = metadata.metadata['Name'], metadata.version
    if name != 'ravel-hep' or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.!+_-]*', version):
        raise ValueError('valid framework package metadata required')
    return {'distribution': name, 'version': version}


def code_version(repository=None):
    source = Path(__file__).resolve().parents[1]
    value = {'ravel_version': _package_metadata()['version'], 'source_commit': None, 'source_modified': None,
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
    return f"""# {manifest['title']}

This package records accepted results and their retained evidence. `submission.json`
lists every file and checksum. Paths are relative to the package directory.
RAVEL version: {code['ravel_version']}.

Run these commands from this directory:

```
make env
make check
make verify
make reproduce
```

`make env` runs `sh environment/setup.sh`. It builds `.venv-analysis` and `.venv-wms` as separate analysis and workflow
environments and links their commands into `.bin/`. Recorded stage packages are in
`environment/analysis-requirements.txt`; framework code is pinned separately in
`environment/ravel-requirements.txt`; workflow packages use a hash lock.
Make adds `.bin/` to PATH. For direct commands, use `export PATH="$PWD/.bin:$PATH"`.
Use the recorded Python version and provision the recorded native runtimes separately.

`make check` runs a Snakemake dry run. `make verify` runs
`ravel export-submission verify --package .`. Add `--fresh-clone` to verify the
package under another parent directory, including a dry run when Snakemake is available.

Fetch inputs listed in `inputs.json` and check their SHA256 before replay.
`make reproduce` selects the `{manifest['layout']['rerun_target']}` workflow target.
It prepares a fresh replay and stops at its approval gate. Read the fresh plan in
`.reproduce/run`, then use the ordinary RAVEL approval interface for that run and
repeat `make reproduce`. Nothing in this package grants approval. Machine approval
is never human approval. Replay compares the new quantities with retained results;
agreement does not establish physics validity or scientific acceptance.

The embedded `procedure/Snakefile` verifies retained evidence using
`ravel procedure verify-node` through PATH. It does not rerun scientific commands.
`run/` and audit metadata contain labelled path projections. Original records that
needed projection are retained byte-for-byte in `original-records/` gzip files;
`submission.json` binds their original sizes and checksums. Those original approvals
remain historical evidence and grant no authority to a fresh replay.
"""


# ---------------------------------------------------------------- release source and layout

_RELEASE_TAG = re.compile(r'v[0-9]+\.[0-9]+(?:\.[0-9]+)?\Z')


def _git_required(checkout, *args):
    done = _git(*args, cwd=checkout)
    if done is None or done.returncode:
        raise ValueError('framework git command failed: ' + (done.stderr.strip() if done else 'git unavailable'))
    return done.stdout


def _relative(value, label, *, dot=False):
    if not _text(value) or '\\' in value or '\n' in value or '\r' in value:
        raise ValueError(label + ' must be a relative path')
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or (not dot and value == '.'):
        raise ValueError(label + ' must be a relative path inside the repository')
    return path.as_posix()


def _layout(layout, subdir):
    if layout is not None and not isinstance(layout, dict):
        layout = json.loads(Path(layout).read_text())
    value = layout if layout is not None else {'schema_version': 1, 'subdir': subdir,
                    'snakefile': str(Path(subdir) / 'Snakefile'), 'rerun_target': 'reproduce', 'required_files': []}
    from jsonschema import Draft202012Validator
    schema = json.loads((Path(__file__).resolve().parents[1] / 'data/submission/layout.schema.json').read_text())
    problems = list(Draft202012Validator(schema).iter_errors(value))
    if problems:
        raise ValueError('invalid submission layout: ' + problems[0].message)
    _relative(value['subdir'], 'layout subdir', dot=True)
    _relative(value['snakefile'], 'layout snakefile')
    for name in value['required_files']: _relative(name, 'layout required file')
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', value['rerun_target']) or value['rerun_target'] in ('all', 'verify'):
        raise ValueError('layout rerun target must be a distinct rule name')
    return dict(value)


def _hook_inputs(checkout, tag, hooks):
    """Read the input provider declared by the tagged hook, without running a build."""
    providers = []
    for name, hook in hooks.items():
        path = hook.get('path', 'hatch_build.py' if name == 'custom' else None)
        if path is None: continue
        source = _git_required(checkout, 'show', f'refs/tags/{tag}:{path}')
        for node in ast.parse(source).body:
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'SUBMISSION_INPUTS' for t in node.targets)):
                providers.append(_relative(ast.literal_eval(node.value), 'hook input provider'))
    if not providers: return []
    done = _git('archive', 'refs/tags/' + tag, cwd=checkout, text=False)
    if done is None or done.returncode:
        raise ValueError('release input census archive failed')
    with tempfile.TemporaryDirectory(prefix='ravel-build-inputs-') as scratch:
        root = Path(scratch)
        with tarfile.open(fileobj=io.BytesIO(done.stdout)) as archive:
            archive.extractall(root, filter='data')
        selected = set(providers)
        for provider in providers:
            # This is the hook's read-only source census, not its initialize/build entry.
            selected.update(run_path(str(root / provider))['input_map'](root))
    return sorted(selected)


def _framework_release(mode, checkout):
    """Read the release tree, not internal export tools or working-tree bytes."""
    if mode != 'vendor' and not (isinstance(mode, str) and mode.startswith('release:')):
        raise ValueError('framework source is vendor or release:<tag>')
    checkout = Path(checkout).resolve() if checkout is not None else Path(__file__).resolve().parents[3]
    top = Path(_git_required(checkout, 'rev-parse', '--show-toplevel').strip()).resolve()
    if checkout.resolve() != top:
        raise ValueError('framework checkout must be a Git checkout root; supply --framework-checkout')
    head = _git_required(checkout, 'rev-parse', 'HEAD').strip()
    tags = sorted(t for t in _git_required(checkout, 'tag', '--points-at', 'HEAD').splitlines() if _RELEASE_TAG.fullmatch(t))
    tag = mode.split(':', 1)[1] if mode != 'vendor' else (tags[0] if tags else '')
    if not _RELEASE_TAG.fullmatch(tag) or tag not in tags:
        raise ValueError('framework HEAD must equal the commit of the requested release tag')
    commit = _git_required(checkout, 'rev-parse', f'refs/tags/{tag}^{{commit}}').strip()
    if commit != head: raise ValueError('framework release tag commit differs from HEAD')
    tree = {}
    for entry in _git_required(checkout, 'ls-tree', '-rz', f'refs/tags/{tag}').split('\0'):
        if not entry: continue
        header, name = entry.split('\t', 1); permissions, kind, blob = header.split()
        tree[name] = {'mode': permissions, 'kind': kind, 'blob_id': blob}
    config = tomllib.loads(_git_required(checkout, 'show', f'refs/tags/{tag}:pyproject.toml'))
    project = config['project']
    if str(project['version']) != _package_metadata()['version']:
        raise ValueError('running RAVEL version differs from release pyproject version')
    url = project['urls']['Repository']
    if not isinstance(url, str) or not re.fullmatch(r'https://[^\s@]+', url):
        raise ValueError('release Repository must be a public HTTPS URL')
    build = config.get('tool', {}).get('hatch', {}).get('build', {})
    includes = build.get('targets', {}).get('sdist', {}).get('include', [])
    if not includes: raise ValueError('release pyproject must declare sdist include paths')
    readme = project.get('readme')
    mandatory = ['pyproject.toml', *(project.get('license-files', []))]
    if isinstance(readme, str): mandatory.append(readme)
    elif isinstance(readme, dict) and 'file' in readme: mandatory.append(readme['file'])
    for name, hook in build.get('hooks', {}).items():
        if 'path' in hook: mandatory.append(hook['path'])
        elif name == 'custom': mandatory.append('hatch_build.py')
    mandatory.extend(_hook_inputs(checkout, tag, build.get('hooks', {})))
    patterns = list(dict.fromkeys([*includes, *mandatory]))
    for pattern in patterns: _relative(pattern, 'release build path')
    def matches(name, pattern):
        return name == pattern or name.startswith(pattern.rstrip('/') + '/') or fnmatch.fnmatchcase(name, pattern)
    excludes = build.get('exclude', []) + build.get('targets', {}).get('sdist', {}).get('exclude', [])
    names = sorted(name for name in tree if any(matches(name, p) for p in patterns)
                   and (any(matches(name, p) for p in mandatory) or not any(matches(name, p) for p in excludes)))
    for pattern in mandatory:
        if not any(matches(name, pattern) for name in names):
            raise ValueError('release required build file missing: ' + pattern)
    for name in names:
        _relative(name, 'release tree file')
        if tree[name]['kind'] != 'blob' or tree[name]['mode'] not in ('100644', '100755'):
            raise ValueError('framework release must ship regular files: ' + name)
    # Both staged and unstaged changes, including deletions, invalidate shipped paths.
    changed = _git_required(checkout, 'diff', '--name-only', '-z', 'HEAD').split('\0')
    staged_new = [name for name in changed if name and any(matches(name, p) for p in patterns)
                  and (any(matches(name, p) for p in mandatory) or not any(matches(name, p) for p in excludes))]
    if staged_new or _git_required(checkout, 'status', '--porcelain', '--untracked-files=no', '--', *names).strip():
        raise ValueError('tracked framework files to be shipped have uncommitted changes')
    return checkout, {'source': mode, 'tag': tag, 'commit': commit, 'url': url,
                      'version': project['version'], 'distribution': project['name'],
                      **({'release_tree': [{'path': name, **tree[name]} for name in names]} if mode == 'vendor' else {})}, names, tree


def _write_framework(pkg, mode, checkout):
    checkout, record, names, tree = _framework_release(mode, checkout)
    if mode == 'vendor':
        # Git archive guarantees bytes from the tag, never modified working-tree files.
        done = _git('archive', 'refs/tags/' + record['tag'], '--', *names, cwd=checkout, text=False)
        if done is None or done.returncode: raise ValueError('framework git archive failed')
        with tarfile.open(fileobj=io.BytesIO(done.stdout)) as archive:
            extracted = {}
            for member in archive.getmembers():
                if member.isdir(): continue
                name = _relative(member.name, 'archive member')
                if not member.isfile() or name not in names or name in extracted:
                    raise ValueError('framework archive file roster differs from release tree')
                raw = archive.extractfile(member).read()
                blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
                if blob != tree[name]['blob_id']: raise ValueError('framework archive blob differs: ' + name)
                path = pkg.root / 'vendor/ravel' / name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw); path.chmod(0o755 if tree[name]['mode'] == '100755' else 0o644)
                pkg.add('vendor/ravel/' + name, 'code')
                extracted[name] = {'path': name, 'sha256': hashlib.sha256(raw).hexdigest(), 'blob_id': blob}
        if set(extracted) != set(names): raise ValueError('framework archive is incomplete')
        scanned = _restricted_source_scan(checkout, record['tag'], pkg.root / 'vendor/ravel')
        pkg.write_json('vendor/ravel/VENDOR-MANIFEST.json',
                       {'tag': record['tag'], 'commit': record['commit'], 'files': list(extracted.values()),
                        'restricted_source_scan': scanned}, 'code')
        requirement = './vendor/ravel\n'
    else:
        requirement = f"{record['distribution']} @ git+{record['url']}@{record['commit']}\n"
    pkg.write('environment/ravel-requirements.txt', requirement, 'environment')
    return record


RESTRICTED_SCAN = 'scripts/maintenance/restricted_source_scan.py'


def _restricted_source_scan(checkout, tag, vendor_root):
    """Run the release's own restricted-source scan over the vendored files; refuse on any finding.

    The owner's deny list comes from the scanner's environment variable (RAVEL_RESTRICTED_SOURCES).
    Without it only the uncited document-hash rule runs; the manifest records which case applied,
    never the list's path or content."""
    done = _git('show', f'refs/tags/{tag}:{RESTRICTED_SCAN}', cwd=checkout, text=False)
    if done is None or done.returncode:
        raise ValueError('framework release carries no restricted-source scan; vendoring refused')
    with tempfile.TemporaryDirectory(prefix='ravel-restricted-scan-') as scratch:
        script = Path(scratch) / 'restricted_source_scan.py'
        script.write_bytes(done.stdout)
        scanner = run_path(str(script))
    supplied = os.environ.get(scanner['ENV'])
    deny_list = None
    if supplied:
        resolved, vendor = Path(supplied).resolve(), Path(vendor_root).resolve()
        if resolved == vendor or vendor in resolved.parents:
            raise ValueError('the restricted-source deny list must live outside the vendored files')
        deny_list = scanner['load_deny_list'](resolved)
    findings = scanner['scan']([vendor_root], deny_list, root=vendor_root)
    if findings:
        paths = sorted({str(f['path']) for f in findings})
        raise ValueError(f'vendored framework files have {len(findings)} restricted-source finding(s): '
                         + ', '.join(paths[:5]) + (' ...' if len(paths) > 5 else ''))
    return {'deny_list': 'supplied' if deny_list is not None else 'none', 'findings': 0}


def _known_roots(rundir, checkout=None):
    roots = {str(Path(rundir).absolute()): 'run', sys.executable: 'python',
             str(Path(__file__).resolve().parents[3]): 'framework', str(Path.home()): 'home'}
    if checkout is not None:
        roots[str(Path(checkout).resolve())] = 'framework'
    # A filesystem anchor (for example HOME=/) names no specific machine location.
    return {root: label for root, label in roots.items() if root and Path(root) != Path(Path(root).anchor)}


def _absolute_paths(text, roots=()):
    """Find only literal exporting-machine roots; slash syntax has no path meaning."""
    return sorted({root for root in roots if root and root in text})


def _project_text(text, rundir, base=None, *, roots=None):
    """Replace known locations literally; never infer a path from slash syntax."""
    locations = _known_roots(rundir) if roots is None else roots
    for root in sorted(locations, key=len, reverse=True):
        if root:
            text = text.replace(root, locations[root])
    return text


def _bounded_text(path):
    if path.stat().st_size > RUN_RECORD_MAX_BYTES:
        return None
    with path.open('rb') as stream:
        raw = stream.read(RUN_RECORD_MAX_BYTES + 1)
    if len(raw) > RUN_RECORD_MAX_BYTES:
        return None
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        return None


def _snapshot_ids(value):
    from .env_snapshot import snapshot_id
    if isinstance(value, dict):
        for child in value.values(): _snapshot_ids(child)
        if value.get('kind') == 'ravel-environment-snapshot': value['snapshot_id'] = snapshot_id(value)
    elif isinstance(value, list):
        for child in value: _snapshot_ids(child)
    return value


def _portable_records(pkg, rundir, *, roots=None):
    projections = []
    for row in list(pkg.files):
        if row['category'] not in ('run', 'audit', 'environment', 'partitions', 'workflow'): continue
        relative = Path(row['path'])
        # Inputs and content-addressed review evidence retain their original bytes.
        if (row['category'] == 'run' and 'inputs' in relative.parts) or relative.suffix == '.blob':
            continue
        path = pkg.root / relative
        text = _bounded_text(path)
        if text is None: continue
        raw = path.read_bytes()
        decoded, structured = text, False
        if path.suffix == '.json':
            try:
                decoded = json.dumps(json.loads(text), ensure_ascii=False); structured = True
            except ValueError: pass
        elif path.suffix == '.jsonl':
            try:
                decoded = '\n'.join(json.dumps(json.loads(line), ensure_ascii=False) for line in text.splitlines() if line.strip()) + '\n'
            except ValueError: pass
        projected = _project_text(decoded, rundir, pkg.base, roots=roots)
        if projected == decoded: continue
        original = 'original-records/' + row['path'] + '.gz'
        saved = pkg.root / original; saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(gzip.compress(raw, mtime=0)); pkg.add(original, 'audit')
        if structured:
            projected = json.dumps(_snapshot_ids(json.loads(projected)), indent=2, sort_keys=True) + '\n'
        path.write_text(projected)
        projections.append({'path': row['path'], 'original': original, 'original_sha256': row['sha256'],
                            'original_size': row['size']})
        row.update(sha256=file_sha256(path), size=path.stat().st_size)
    return projections


def _embedded_procedure(pkg, rundir, references, *, known_roots=None):
    from . import procedure_export as pe
    document = pe.build(rundir)
    run_roots = {str(rundir): 'run'}
    for root in document.get('run_dirs', []):
        if root == str(rundir): continue
        folder = 'run/children/' + hashlib.sha256(root.encode()).hexdigest()[:16]
        run_roots[root] = folder
        _copy_run(pkg, Path(root), references, prefix=folder)
    file_paths = {}
    # Retain evidence from the run and from supplied sources outside it.
    for pin in document['source_pins']:
        source = Path(pin['path'])
        target = None
        for root in sorted(run_roots, key=len, reverse=True):
            if source.is_relative_to(root):
                target = run_roots[root] + '/' + source.relative_to(root).as_posix(); break
        if target is None:
            target = 'run/evidence/' + hashlib.sha256(str(source).encode()).hexdigest() + '/' + source.name
        file_paths[str(source)] = target
        copied = pkg.root / target
        if not copied.is_file():
            if source.stat().st_size > RUN_RECORD_MAX_BYTES:
                raise ValueError('embedded procedure evidence exceeds package byte ceiling: ' + source.name)
            pkg.copy(source, target, 'run')
        if copied.stat().st_size != pin['size'] or (pin['sha256'] is not None and file_sha256(copied) != pin['sha256']):
            raise ValueError('procedure evidence changed during copy: ' + source.name)
    roots = {**(known_roots or _known_roots(rundir)), **run_roots}
    projections = _portable_records(pkg, rundir, roots=roots)
    def project(value):
        if isinstance(value, dict):
            out = {project(k): project(v) for k, v in value.items()}
            if {'path', 'sha256', 'size'} <= value.keys() and str(value['path']) in file_paths:
                target_name = file_paths[str(value['path'])]
                target = pkg.root / target_name
                out.update(path='../' + target_name, sha256=file_sha256(target), size=target.stat().st_size,
                           original_sha256=value['sha256'], original_size=value['size'])
            return _snapshot_ids(out)
        if isinstance(value, list): return [project(v) for v in value]
        if isinstance(value, str):
            result = _project_text(value, rundir, pkg.base, roots=roots)
            return '../' + result if Path(value).is_absolute() and (result == 'run' or result.startswith('run/')) else result
        return value
    document = project(document)
    document['path_basis'] = 'package-relative'
    document['limitations'] = [line for line in document['limitations'] if 'Standalone exports' not in line]
    document['limitations'].append('Package path projections bind relocated files; compressed originals retain source approval evidence and grant no fresh execution authority.')
    document['record_roster'] = sorted(document['record_roster'])
    for row in projections:
        pin = pe._source(pkg.root / row['original']); pin['path'] = '../' + row['original']
        document['source_pins'].append(pin)
    pe.export(rundir, pkg.root / 'procedure', _document=document)
    for path in sorted((pkg.root / 'procedure').rglob('*')):
        if path.is_file(): pkg.add(path.relative_to(pkg.root), 'workflow')
    return projections


def _replay_rules(target):
    """Consume the public template API; absent integration stays behind a CLI seam."""
    try:
        from . import replay
    except ImportError as exc:
        if exc.name not in (__package__, __package__ + '.replay'): raise
        return f'''# Public replay interface is required at execution time.
rule {target}:
    output: ".reproduce/replay-comparison.json"
    shell: "mkdir -p .reproduce && ravel replay template > .reproduce/replay.smk && cd .reproduce && snakemake --cores 1 -s replay.smk --config original=.. replay=run"
'''
    text = replay.template_text().replace('rule all:', f'rule {target}:')
    for name in ('replay-prepared.json', 'replay-approved.json', 'replay-run.json', 'replay-comparison.json'):
        text = text.replace('"' + name + '"', '".reproduce/' + name + '"')
    return 'config.setdefault("original", ".")\nconfig.setdefault("replay", ".reproduce/run")\n' + text


def _makefile(layout):
    return f'''# Run from this package directory. Export never executes these targets.
export PATH := ${{CURDIR}}/.bin:$(PATH)
.PHONY: env check verify reproduce
env:
\tPYTHONDONTWRITEBYTECODE=1 sh environment/setup.sh
check:
\tsnakemake -n --cores 1 --snakefile Snakefile
verify:
\travel export-submission verify --package .
reproduce:
\tsnakemake --cores 1 --snakefile Snakefile {layout['rerun_target']}
'''


# ---------------------------------------------------------------- export

def export(request_path, into, *, subdir='submission', rules=None, layout=None,
           framework_source=None, framework_checkout=None):
    """Write a submission package into `into/subdir`; return its summary."""
    request_path = Path(request_path).absolute()
    request = validate_request(json.loads(request_path.read_text()))
    rules_value = validate_rules(json.loads(Path(rules).read_text())) if rules is not None else None
    layout_value = _layout(layout, subdir)
    repository = Path(into).absolute()
    root = repository / layout_value['subdir']
    snake_location = repository / layout_value['snakefile']
    if not root.resolve().is_relative_to(repository.resolve()) or not snake_location.resolve().is_relative_to(repository.resolve()):
        raise ValueError('layout path points outside repository')
    external_snake = not snake_location.is_relative_to(root)
    if external_snake and snake_location.exists():
        raise ValueError('layout Snakefile must be a fresh path')
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
        for pin in environment_lock(rundir, pkg.root):
            pkg.add(pin['path'], 'environment')
        partitions = _partitions(pkg, request['partitions'])
        site = _site(pkg, request['site_workflow'])
        pkg.write_json('workflow/dag.json', workflow_graph(rundir, partitions, site), 'workflow')
        audit = _audit(pkg, request['audit'], rundir)
        framework = _write_framework(pkg, framework_source, framework_checkout) if framework_source is not None else None
        if framework is None:
            framework = {'source': 'distribution', **_package_metadata()}
            pkg.write('environment/ravel-requirements.txt',
                      f"{framework['distribution']}=={framework['version']}\n", 'environment')
        known_roots = _known_roots(rundir, framework_checkout)
        projections = _embedded_procedure(pkg, rundir, references, known_roots=known_roots)
        pkg.write_json('inputs.json', {'schema_version': 1, 'kind': 'ravel-input-references', 'inputs': references}, 'inputs')
        manifest = {'schema_version': SCHEMA_VERSION, 'kind': 'ravel-submission', 'title': request['title'],
                    'created_utc': utc_now(), 'acceptance': acceptance,
                    'code_version': code_version(request['code_repository']),
                    'inputs': references, 'audit': audit, 'files': [], 'layout': layout_value,
                    'framework': framework, 'path_projections': projections,
                    'record_scope': 'Path projections are portable metadata; compressed originals are historical evidence, not fresh approval.',
                    'machine_approval_is_not_human_review': True}
        manifest['files'] = pkg.files
        pkg.write('REPRODUCE.md', _reproduce(manifest), 'reproduce')
        pkg.write('Snakefile', SNAKEFILE + '\n' + _replay_rules(layout_value['rerun_target']), 'reproduce')
        if not external_snake and snake_location != root / 'Snakefile':
            relative = snake_location.relative_to(root).as_posix()
            depth = len(Path(relative).parts) - 1
            pkg.write(relative, f'include: {repr("../" * depth + "Snakefile")}\n', 'reproduce')
        pkg.write('Makefile', _makefile(layout_value), 'reproduce')
        for required in layout_value['required_files']:
            if not (pkg.root / required).is_file(): raise ValueError('layout required file missing: ' + required)
        manifest['files'] = sorted(pkg.files, key=lambda r: r['path'])
        if rules_value is not None:
            manifest['rules'] = {'sha256': file_sha256(rules), 'origin': Path(rules).name}
            errors = rule_errors(manifest, rules_value)
            if errors:
                raise ValueError('; '.join(errors))
        with (staging / MANIFEST).open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + '\n')
        from ravel.physics.manuscript_assets import refuse_public_assets
        refuse_public_assets(staging, metadata=[request_path, *[pkg.resolve(row['path']) for row in request['inputs'] if 'path' in row]],
                             exclude=('vendor/ravel',))
        preliminary = _check(staging, roots=known_roots)
        if not preliminary['passed']: raise ValueError('package portability check failed: ' + '; '.join(preliminary['errors']))
        if root.exists():
            root.rmdir()
        root.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(root)
        if external_snake:
            snake_location.parent.mkdir(parents=True, exist_ok=True)
            include = os.path.relpath(root / 'Snakefile', snake_location.parent)
            workdir = os.path.relpath(root, repository)
            with snake_location.open('x') as stream:
                stream.write(f'workdir: {workdir!r}\ninclude: {include!r}\n')
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    report = verify(root, fresh_clone=False)
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

def _work_path(relative):
    return relative.startswith(WORK_DIRS) or '.snakemake' in Path(relative).parts[:-1]


def _installed_command(package, relative, path):
    targets = {'.bin/ravel': '../.venv-analysis/bin/ravel',
               '.bin/snakemake': '../.venv-wms/bin/snakemake'}
    if relative not in targets or not path.is_symlink() or os.readlink(path) != targets[relative]:
        return False
    if not path.is_file(): return False
    tracked = _git('ls-files', '--error-unmatch', '--', relative, cwd=package)
    return tracked is None or tracked.returncode != 0


def _check(package, *, roots=()):
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
            if relative not in listed and relative not in GENERATED and not _work_path(relative) and not _installed_command(package, relative, path):
                errors.append(f'{relative} is in the package but not listed in {MANIFEST}')
    # Export checks only known machine roots, within the inherited read ceiling.
    # Later verification relies on the complete sha256 listing.
    if roots:
        for path in package.rglob('*'):
            relative = path.relative_to(package).as_posix()
            if _work_path(relative) or path.is_symlink() or not path.is_file(): continue
            # Content-addressed snapshots are opaque historical evidence, like gzip originals.
            if path.suffix == '.blob' and 'snapshots' in path.parts and _hex64(path.stem):
                if file_sha256(path) != path.stem:
                    errors.append(f'{relative} differs from its content-addressed name')
                continue
            text = _bounded_text(path)
            if text is None: continue
            decoded = ''
            if path.suffix in ('.json', '.jsonl'):
                try:
                    values = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == '.jsonl' else [json.loads(text)]
                    decoded = '\n'.join(json.dumps(v, ensure_ascii=False) for v in values)
                except ValueError: pass
            for absolute in _absolute_paths(text + decoded, roots):
                errors.append(f'{relative} names an absolute path: {absolute}')
    for projection in manifest.get('path_projections', []):
        try:
            original = package / _relative(projection['original'], 'original record')
            raw = gzip.decompress(original.read_bytes())
            if len(raw) != projection['original_size'] or hashlib.sha256(raw).hexdigest() != projection['original_sha256']:
                errors.append('original record differs: ' + projection['original'])
        except (OSError, ValueError, KeyError, EOFError):
            errors.append('original record is missing or invalid')
    framework = manifest.get('framework') or {}
    if framework:
        mode = framework.get('source')
        expected_pin = ('./vendor/ravel\n' if mode == 'vendor' else
                        f"{framework['distribution']}=={framework['version']}\n" if mode == 'distribution' else
                        f"{framework['distribution']} @ git+{framework['url']}@{framework['commit']}\n")
        pin = package / 'environment/ravel-requirements.txt'
        if not pin.is_file() or pin.read_text() != expected_pin:
            errors.append('framework pin differs from submission identity')
        if manifest.get('code_version', {}).get('ravel_version') != framework.get('version'):
            errors.append('framework pin version differs from exporting package metadata')
    vendor = package / 'vendor/ravel'
    if (vendor / 'VENDOR-MANIFEST.json').is_file():
        try:
            vmanifest = json.loads((vendor / 'VENDOR-MANIFEST.json').read_text())
            framework = manifest.get('framework') or {}
            tree = {row['path']: row['blob_id'] for row in framework.get('release_tree', [])}
            if vmanifest['tag'] != framework.get('tag') or vmanifest['commit'] != framework.get('commit'):
                errors.append('vendor release identity differs from submission manifest')
            expected = {'VENDOR-MANIFEST.json'}
            for row in vmanifest['files']:
                name = _relative(row['path'], 'vendor file'); expected.add(name)
                path = vendor / name
                if path.is_symlink(): raise ValueError('vendor symlink')
                raw = path.read_bytes()
                blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
                if hashlib.sha256(raw).hexdigest() != row['sha256'] or blob != row['blob_id'] or blob != tree.get(name):
                    errors.append('vendored file differs from release manifest: ' + name)
            actual = {p.relative_to(vendor).as_posix() for p in vendor.rglob('*') if p.is_file() or p.is_symlink()}
            if actual != expected: errors.append('vendor file roster differs from release manifest')
        except (OSError, ValueError, KeyError): errors.append('vendor manifest is invalid or incomplete')
    for name in (manifest.get('layout') or {}).get('required_files', []):
        try:
            if not (package / _relative(name, 'layout required file')).is_file():
                errors.append('layout required file missing: ' + name)
        except ValueError as exc: errors.append(str(exc))
    if (package / 'procedure/procedure.json').is_file():
        from .procedure_export import verify as verify_procedure
        try: verify_procedure(package / 'procedure', deep=True)
        except (OSError, ValueError, KeyError) as exc:
            errors.append('procedure evidence check failed: ' + str(exc))
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


def verify(package, *, fresh_clone=True):
    """Check a package; with fresh_clone, check it again in a fresh clone or copy."""
    package = Path(package).absolute()
    report = _check(package)
    if not fresh_clone or not package.is_dir():
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
            def ignore_work(directory, names):
                relative = Path(directory).relative_to(package)
                return [name for name in names if name == '.snakemake' or
                        _work_path((relative / name).as_posix() + '/') or
                        relative == Path('.') and name == '.bin']
            shutil.copytree(package, fresh, symlinks=True, ignore=ignore_work)
            method = 'copy'
        second = _check(fresh)
        dry_run = snakemake_dry_run(fresh)
    if dry_run['status'] == 'failed':
        second['errors'].append('snakemake dry run failed: ' + dry_run['detail'])
    elif dry_run['status'] == 'not-installed':
        report['warnings'].append('snakemake is not installed here; the workflow dry run was not performed')
    report['fresh_clone'] = {'method': method, 'checked': True, 'passed': not second['errors'], 'snakemake': dry_run}
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
    parser.add_argument('--layout', type=Path, help='repository layout JSON')
    parser.add_argument('--framework-source', help='release:<tag> or vendor')
    parser.add_argument('--framework-checkout', type=Path, help='local tagged RAVEL checkout')
    args = parser.parse_args(argv)
    try:
        result = export(args.request, args.into, subdir=args.subdir, rules=args.rules, layout=args.layout,
                        framework_source=args.framework_source, framework_checkout=args.framework_checkout)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f'export submission: {exc}\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
