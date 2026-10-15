"""Transport registry: declared routes from a role to a model, probed before use.

A transport is one JSON declaration (``src/ravel/data/transports/<id>.json``, or the
user's own under ``.ravel/transports/`` or ``$RAVEL_TRANSPORT_PATH``). It names the
launcher and its argv template, the models it serves, how it authenticates, which
environment variable names it passes, how it is billed and what it can do. A CLI
transport's capabilities count only after ``probe`` has run the installed CLI's
``--version`` and ``--help`` successfully, found every flag of the template and
recorded the executable's path and sha256; a probe of another executable is stale.
Help text confirms flags only: tools, isolation and attestation are never confirmed
from it. Selection walks the run's preference list for the role's family and takes
the first transport whose effective capabilities meet the role card's ``requires``;
otherwise it raises ``TransportRefusal`` naming what is missing, before any process
starts. Effective capabilities are also capped by where a declaration came from: a
declaration under ``.ravel/transports`` or ``$RAVEL_TRANSPORT_PATH`` cannot claim
blind review or isolation above ``cli-policy``, and a sandbox isolation counts only
when the sandbox module exists and the declaration is ``live_qualified``.

Declarations hold variable names only, never values. A token command's output is
used for one request and never written anywhere.
"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tempfile
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
BUILTIN_DIR = Path(__file__).resolve().parents[1] / 'data' / 'transports'
MODEL_CLASSES = BUILTIN_DIR / 'index' / 'model-classes.json'

TRANSPORT_KINDS = ('http-model', 'external-relay', 'cli-oneshot', 'cli-worker', 'ravel-loop', 'host-subagent', 'stub')
CLI_KINDS = ('cli-oneshot', 'cli-worker')
AUTH_KINDS = ('login', 'env', 'command', 'none')
HEADER_STYLES = ('bearer', 'x-api-key', 'x-goog-api-key', 'api-key')
BILLING = ('subscription', 'api', 'local', 'none')
TOOLS = ('none', 'broker-readonly', 'broker-full')
# os-sandbox-readonly confines writes only; the session can still read the filesystem.
ISOLATION = ('none', 'cli-policy', 'os-sandbox-readonly', 'ravel-sandbox', 'os-sandbox')
ATTESTATION = ('self', 'host', 'transport')
TIERS = ('judgment', 'agent', 'cheap')
QUALIFICATION = ('declared', 'stub_tested', 'probed', 'live_qualified')
BOOLEAN_CAPABILITIES = ('structured_output', 'blind_capable', 'effort_control', 'session_id', 'usage_report')
CAPABILITY_KEYS = {'tools', 'isolation', 'attestation', *BOOLEAN_CAPABILITIES}
DECLARATION_KEYS = {'schema_version', 'kind', 'id', 'transport_kind', 'launcher', 'argv_template', 'models', 'auth',
                    'pass_env', 'billing', 'capabilities', 'max_concurrent', 'qualification'}
OPTIONAL_KEYS = {'endpoint', 'notes', 'worker_surface', 'account_class'}
# how a CLI worker loads the broker MCP face and how its final record is checked.
MCP_CONFIGS = ('mcp_config_flag', 'codex_home', 'settings_json', 'opencode_config', 'probe_required')
STRUCTURED_OUTPUT = ('enforced', 'validated_text')
BLIND_KINDS = ('http-model', 'ravel-loop', 'external-relay')
SECRET_NAME = re.compile(r'(_API_KEY|_AUTH_TOKEN|_TOKEN|_SECRET)$|^(ANTHROPIC|OPENAI)_')
NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
IDENT = re.compile(r'^[a-z0-9][a-z0-9.-]{0,79}$')
PLACEHOLDER = re.compile(r'\{([a-z_]+)\}')
SANDBOX_ISOLATION = ('ravel-sandbox', 'os-sandbox')
# Modules that must exist before a declaration of this kind can claim a sandbox.
SANDBOX_MODULES = ('ravel.workflow.sandbox',)
# Routes whose launch configuration is not generated yet; selection refuses them with the reason.
UNIMPLEMENTED_ROUTES = {'codex-cli-worker-azure': 'the Azure model_provider configuration is not generated yet'}
# The executor a transport kind needs. A kind whose executor is absent is not selectable.
EXECUTOR_MODULES = {'cli-worker': ('ravel.workflow.agent_worker', 'ravel.workflow.transports.cli_worker'),
                    'ravel-loop': ('ravel.workflow.transports.ravel_loop',),
                    'host-subagent': ('ravel.workflow.transports.host_subagent',)}
# Kinds whose executor runs the model inside the RAVEL sandbox; without a sandbox backend they are not selectable.
SANDBOXED_KINDS = ('cli-worker',)
# The adapter that says which declarations of a kind it can launch (``unsupported(document)``).
ADAPTER_MODULES = {'cli-worker': 'ravel.workflow.transports.cli_worker',
                   'host-subagent': 'ravel.workflow.transports.host_subagent'}
QUALIFICATION_RECORD_KEYS = {'schema_version', 'kind', 'transport_id', 'status', 'record_path', 'executable_path',
                             'executable_sha256', 'declaration_sha256', 'probe_sha256', 'receipt', 'observed',
                             'steps', 'rundir', 'qualified_utc'}
MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,199}$')
PROBE_KEYS = {'schema_version', 'kind', 'transport_id', 'declaration_sha256', 'cli_version', 'help_sha256', 'flags',
              'capabilities_confirmed', 'unusable', 'probed_utc', 'executable_path', 'executable_sha256', 'exit_status'}
FAMILY_PATTERNS = (('anthropic', ('claude',)), ('openai', ('gpt', 'codex', 'o1', 'o3', 'o4', 'davinci')),
                   ('google', ('gemini', 'gemma')), ('xai', ('grok',)), ('meta', ('llama',)),
                   ('alibaba', ('qwen',)), ('mistral', ('mistral', 'mixtral', 'codestral')),
                   ('deepseek', ('deepseek',)))


class TransportRefusal(ValueError):
    """No declared transport meets the role's requirements; raised before any process starts."""
    not_dispatched = True  # the effect ledger may retry the path (nothing was sent)

    def __init__(self, message, missing):
        super().__init__(message)
        self.missing = list(missing)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def _fail(identity, message):
    raise ValueError(f'transport {identity}: {message}')


def validate(document):
    """Check one declaration against the closed shape; return it unchanged."""
    identity = document.get('id', '?') if type(document) is dict else '?'
    if type(document) is not dict:
        _fail(identity, 'declaration must be an object')
    if document.get('schema_version') != SCHEMA_VERSION or document.get('kind') != 'transport':
        _fail(identity, 'unknown schema_version or kind')
    missing, extra = DECLARATION_KEYS - set(document), set(document) - DECLARATION_KEYS - OPTIONAL_KEYS
    if missing or extra:
        _fail(identity, f'missing {sorted(missing)} or unknown {sorted(extra)} fields')
    if type(identity) is not str or not IDENT.match(identity):
        _fail(identity, 'id must be lower-case letters, digits, dots and hyphens')
    if 'account_class' in document and (type(document['account_class']) is not str
                                       or not IDENT.fullmatch(document['account_class'])):
        _fail(identity, 'account_class must be an explicit lower-case identifier')
    kind = document['transport_kind']
    if kind not in TRANSPORT_KINDS:
        _fail(identity, f'transport_kind must be one of {TRANSPORT_KINDS}')
    template, launcher = document['argv_template'], document['launcher']
    if type(template) is not list or any(type(a) is not str for a in template):
        _fail(identity, 'argv_template must be a list of strings')
    if kind in CLI_KINDS:
        if type(launcher) is not str or not launcher or not template or template[0] != launcher:
            _fail(identity, 'a CLI transport names its launcher as the first argv element')
    elif launcher is not None and type(launcher) is not str:
        _fail(identity, 'launcher must be a string or null')
    models = document['models']
    if type(models) is not list or not models:
        _fail(identity, 'models must be a nonempty list')
    for model in models:
        if (type(model) is not dict or set(model) != {'id', 'family', 'tiers'} or type(model['id']) is not str
                or type(model['family']) is not str or type(model['tiers']) is not list or not model['tiers']
                or set(model['tiers']) - set(TIERS)):
            _fail(identity, 'each model is {id, family, tiers} with tiers from ' + ', '.join(TIERS))
    auth = document['auth']
    if type(auth) is not dict or set(auth) != {'kind', 'env_names', 'command', 'header_style'}:
        _fail(identity, 'auth is {kind, env_names, command, header_style}')
    if auth['kind'] not in AUTH_KINDS:
        _fail(identity, f'auth.kind must be one of {AUTH_KINDS}')
    for names in (auth['env_names'], document['pass_env']):
        if type(names) is not list or any(type(n) is not str or not NAME.match(n) for n in names):
            _fail(identity, 'environment entries are variable names')
    if auth['kind'] == 'command':
        if type(auth['command']) is not list or not auth['command'] or any(type(a) is not str or not a for a in auth['command']):
            _fail(identity, 'a command auth names its token program as an argument list')
    elif auth['command'] is not None:
        _fail(identity, 'auth.command is only for kind command')
    if auth['kind'] == 'env' and not auth['env_names']:
        _fail(identity, 'env auth names at least one variable')
    style = auth['header_style']
    if kind == 'http-model' and auth['kind'] != 'none' and style not in HEADER_STYLES:
        _fail(identity, f'an authenticated HTTP transport declares header_style from {HEADER_STYLES}')
    if style is not None and (kind not in ('http-model', 'ravel-loop') or style not in HEADER_STYLES):
        _fail(identity, 'header_style applies to HTTP transports only')
    if document['billing'] not in BILLING:
        _fail(identity, f'billing must be one of {BILLING}')
    capabilities = document['capabilities']
    if type(capabilities) is not dict or set(capabilities) != CAPABILITY_KEYS:
        _fail(identity, f'capabilities are exactly {sorted(CAPABILITY_KEYS)}')
    for key, allowed in (('tools', TOOLS), ('isolation', ISOLATION), ('attestation', ATTESTATION)):
        if capabilities[key] not in allowed:
            _fail(identity, f'capabilities.{key} must be one of {allowed}')
    if any(type(capabilities[k]) is not bool for k in BOOLEAN_CAPABILITIES):
        _fail(identity, 'boolean capabilities must be true or false')
    if type(document['max_concurrent']) is not int or not 1 <= document['max_concurrent'] <= 64:
        _fail(identity, 'max_concurrent must be an integer from 1 to 64')
    qualification = document['qualification']
    if (type(qualification) is not dict or set(qualification) != {'status', 'record'}
            or qualification['status'] not in QUALIFICATION):
        _fail(identity, f'qualification is {{status, record}} with status from {QUALIFICATION}')
    endpoint = document.get('endpoint')
    if endpoint is not None:
        if kind not in ('http-model', 'ravel-loop') or type(endpoint) is not str or not _endpoint_ok(endpoint):
            _fail(identity, 'endpoint must be an HTTPS URL, or loopback HTTP, on an HTTP transport')
    if 'notes' in document and type(document['notes']) is not str:
        _fail(identity, 'notes must be text')
    surface = document.get('worker_surface')
    if surface is not None:
        mcp = surface.get('mcp') if type(surface) is dict else None
        if (kind != 'cli-worker' or set(surface) != {'mcp', 'structured_output'} or type(mcp) is not dict
                or set(mcp) != {'config', 'argv'} or mcp['config'] not in MCP_CONFIGS
                or type(mcp['argv']) is not list or any(type(a) is not str for a in mcp['argv'])
                or surface['structured_output'] not in STRUCTURED_OUTPUT
                or (surface['structured_output'] == 'enforced') != capabilities['structured_output']):
            _fail(identity, 'worker_surface is {mcp: {config, argv}, structured_output} on a cli-worker; '
                  'enforced structured output needs capabilities.structured_output true')
    return document


def _endpoint_ok(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return parsed.scheme == 'https' or (parsed.scheme == 'http' and is_loopback(url))


def is_loopback(url):
    """Literal loopback destinations only; no name resolution."""
    host = urlsplit(url).hostname
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False


def search_dirs():
    """Built-ins first, then the user's directories; a later file with the same id is refused."""
    dirs = [BUILTIN_DIR]
    for entry in filter(None, os.environ.get('RAVEL_TRANSPORT_PATH', '').split(os.pathsep)):
        dirs.append(Path(entry).expanduser())
    local = Path.cwd() / '.ravel' / 'transports'
    if local.is_dir():
        dirs.append(local)
    return dirs


_ORIGINS = {}


def all_declarations():
    found = {}
    for directory in search_dirs():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob('*.json')):
            document = validate(json.loads(path.read_text(encoding='utf-8')))
            if document['id'] in found:
                raise ValueError(f'transport {document["id"]} is declared twice ({path})')
            if path.stem != document['id']:
                raise ValueError(f'transport file {path.name} must be named after its id')
            found[document['id']] = document
            _ORIGINS[document['id']] = 'builtin' if directory == BUILTIN_DIR else str(path)
    return [found[k] for k in sorted(found)]


def origin(document):
    """'builtin' for a shipped declaration, else the user file it was read from."""
    identity = document['id']
    if identity not in _ORIGINS:
        all_declarations()
    builtin = BUILTIN_DIR / f'{identity}.json'
    if _ORIGINS.get(identity) == 'builtin' and builtin.is_file():
        try:
            if declaration_sha256(validate(json.loads(builtin.read_text(encoding='utf-8')))) == declaration_sha256(document):
                return 'builtin'
        except ValueError:
            pass
        return 'modified'
    return _ORIGINS.get(identity, 'unknown')


def _importable(names):
    import importlib.util
    try:
        return all(importlib.util.find_spec(name) is not None for name in names)
    except (ImportError, ValueError):
        return False


def sandbox_available():
    """True when every module a sandbox isolation claim depends on is importable."""
    return _importable(SANDBOX_MODULES)


def executor_problem(document):
    """Why this installation cannot execute the transport (None when it can).

    The executor modules must import; a sandboxed kind also needs a sandbox backend on this
    host; and the kind's adapter must support the declaration (it names what is missing).
    """
    kind = document['transport_kind']
    if not _importable(EXECUTOR_MODULES.get(kind, ())):
        return 'unimplemented:' + kind
    if kind in SANDBOXED_KINDS:
        from . import sandbox
        if sandbox.available() is None:
            return 'sandbox_unavailable'
    if kind in ADAPTER_MODULES:
        import importlib
        return importlib.import_module(ADAPTER_MODULES[kind]).unsupported(document)
    return None


def executor_available(document):
    """True when the executor this transport kind needs exists and can run this declaration here."""
    return executor_problem(document) is None


def load(transport_id):
    for document in all_declarations():
        if document['id'] == transport_id:
            return document
    raise KeyError(f'no transport declaration {transport_id!r}')


def declaration_sha256(document):
    return digest(document)


def model_family(model_id):
    """The vendor family a model identifier names, or 'unknown'."""
    text = str(model_id or '').lower()
    for family, needles in FAMILY_PATTERNS:
        if any(re.search(r'(^|[^a-z])' + re.escape(n), text) for n in needles):
            return family
    return 'unknown'


def family_of(document, model_id, bindings=None):
    """The family of a model on a transport: an exact declared id, an explicit binding, then the identifier.

    A ``{configured}`` entry never lends its family to a model whose identifier names another family.
    """
    for model in document['models']:
        if model['id'] == model_id and model['family'] != 'any':
            return model['family']
    bound = (bindings or {}).get(model_id)
    if type(bound) is str and bound:
        return bound
    return model_family(model_id)


def model_problem(document, model_id, bindings=None):
    """Why a model id cannot run on this transport (None when it can).

    The id must be an exact declared id, or fit a ``{configured}`` entry of the same family; a family
    the identifier does not reveal needs an explicit binding in the run preferences.
    """
    if type(model_id) is not str or not MODEL_ID.match(model_id):
        return 'model:invalid'
    if any(m['id'] == model_id for m in document['models']):
        return None
    open_entries = [m for m in document['models'] if '{' in m['id']]
    if not open_entries:
        return 'model:undeclared'
    family = family_of(document, model_id, bindings)
    if any(m['family'] in ('any', family) for m in open_entries) and family != 'unknown':
        return None
    return 'model:family' if family != 'unknown' else 'model:family-unbound'


# ------------------------------------------------------------ argv and environment

def template_flags(document):
    """The option flags an argv template uses (tokens that start with a dash)."""
    return [a for a in document['argv_template'][1:] if a.startswith('-') and a != '-' and not PLACEHOLDER.search(a)]


def render_argv(document, values, *, executable=None):
    """Fill an argv template. A flag whose sole value placeholder is None is dropped with that value."""
    template, out, index = document['argv_template'], [], 0
    while index < len(template):
        item = template[index]
        following = template[index + 1] if index + 1 < len(template) else None
        whole = PLACEHOLDER.fullmatch(following or '')
        if item.startswith('-') and whole and values.get(whole.group(1), '') is None:
            index += 2
            continue
        names = PLACEHOLDER.findall(item)
        for name in names:
            if name not in values:
                raise KeyError(f'argv placeholder {{{name}}} has no value')
            if values[name] is None:
                raise KeyError(f'argv placeholder {{{name}}} is required')
        out.append(PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), item))
        index += 1
    if executable:
        out[0] = str(executable)
    return out


BASE_ENVIRONMENT = ('HOME', 'PATH', 'LANG', 'LC_ALL', 'USER', 'LOGNAME', 'TMPDIR', 'SHELL', 'TERM',
                    'SSL_CERT_FILE', 'HTTPS_PROXY', 'HTTP_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy', 'no_proxy')
PROXY_NAMES = ('HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy')


def _without_credentials(url):
    """A proxy URL with any user:password removed."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.username is None and parsed.password is None:
        return url
    host = parsed.hostname or ''
    if ':' in host:
        host = f'[{host}]'
    try:
        port = parsed.port
    except ValueError:
        return None
    netloc = host + (f':{port}' if port else '')
    return parsed._replace(netloc=netloc).geturl()


def child_environment(document, environment=None):
    """The child's environment: the base allowlist plus the declared names, nothing else.

    Returns (env, passed_names). Undeclared credential-like names never pass, and proxy URLs lose
    any embedded user name and password. PYTHONPATH and XDG_CONFIG_HOME are not passed.
    """
    source = dict(os.environ if environment is None else environment)
    declared = set(document['pass_env']) | set(document['auth']['env_names'])
    env = {}
    for name in sorted(set(BASE_ENVIRONMENT) | declared):
        if name in source and (name in declared or not SECRET_NAME.search(name)):
            value = source[name]
            if name in PROXY_NAMES and name not in declared:
                value = _without_credentials(value)
                if value is None:
                    continue
            env[name] = value
    return env, sorted(env)


# ------------------------------------------------------------ probe

def state_dir():
    configured = os.environ.get('RAVEL_STATE_DIR')
    return (Path(configured).expanduser() if configured else Path.home() / '.local/state/ravel') / 'transports'


def probe_path(transport_id):
    return state_dir() / f'{transport_id}.probe.json'


def _help_command(document, executable):
    """``--help`` of the subcommand the template uses (``codex exec --help``, ``opencode run --help``)."""
    prefix = []
    for word in document['argv_template'][1:]:
        if word.startswith('-') or PLACEHOLDER.search(word):
            break
        prefix.append(word)
    return [executable, *prefix, '--help']


def _flag_present(flag, text):
    return re.search(r'(?<![\w-])' + re.escape(flag) + r'(?![\w-])', text) is not None


def file_sha256(path):
    digest_ = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest_.update(block)
    return digest_.hexdigest()


def resolve_executable(document, environment=None, executable=None):
    """(absolute path, sha256) of the launcher a CLI transport would run now, or (None, None)."""
    env, _ = child_environment(document, environment)
    path = executable or shutil.which(document['launcher'], path=env.get('PATH'))
    if not path:
        return None, None
    path = str(Path(path).resolve())
    try:
        return path, file_sha256(path)
    except OSError:
        return None, None


def _carrier_confirmed(document, placeholder, flags):
    """True when the template flag that carries ``{placeholder}`` was found in --help."""
    template = document['argv_template']
    for index, token in enumerate(template):
        if '{' + placeholder + '}' in token:
            flag = token.split('=', 1)[0] if token.startswith('-') else (template[index - 1] if index else '')
            return flags.get(flag) == 'confirmed'
    return False


def check_executable_location(path, *, rundir=None, project_root=None):
    """Refuse probe programs in agent/run, source-project or temporary storage."""
    path = Path(path).resolve()
    trusted = os.environ.get('RAVEL_TEST_TRUSTED_BIN')
    if trusted:
        # Fake test programs are trusted only inside a test lock domain this process's harness
        # selected or validated; the variable alone exempts nothing.
        from . import machine_lease
        if machine_lease.domain() == 'test' and path.is_relative_to(Path(trusted).resolve()):
            return
    cwd = Path.cwd().resolve()
    projects = [Path(project_root).resolve()] if project_root else []
    source = Path(__file__).resolve().parents[3]
    if (source / 'pyproject.toml').is_file():
        projects.append(source)
    projects.extend(p for p in (cwd, *cwd.parents) if (p / 'pyproject.toml').is_file())
    locations = [('run', Path(rundir).resolve())] if rundir else []
    locations += [('project', p) for p in projects]
    # The current directory stands in for the run, unless it is the home directory or one of its ancestors.
    if not Path.home().resolve().is_relative_to(cwd):
        locations += [('run', cwd)]
    if os.environ.get('TMPDIR'):
        locations.append(('TMPDIR', Path(os.environ['TMPDIR']).resolve()))
    locations += [('temporary', Path(tempfile.gettempdir()).resolve()), ('temporary', Path('/tmp').resolve())]
    for label, directory in locations:
        if path.is_relative_to(directory):
            raise TransportRefusal(f'probe executable is under the {label} directory: {directory}',
                                   [f'executable:{label}'])


def probe(transport_id, *, write=True, executable=None, environment=None, timeout=30, rundir=None, project_root=None):
    """Read the CLI's version and --help; confirm every template flag. Never sends a prompt.

    A failing ``--version`` or ``--help`` confirms nothing. The record binds the executable's resolved
    path and sha256. Help text can confirm that a flag exists, so structured output and effort control
    count only when the flag that carries them is confirmed; tools, isolation, attestation and blind
    review are never confirmed by a probe.
    """
    document = load(transport_id)
    record = {'schema_version': 1, 'kind': 'transport-probe', 'transport_id': transport_id,
              'declaration_sha256': declaration_sha256(document), 'cli_version': None, 'help_sha256': None,
              'flags': {}, 'capabilities_confirmed': {}, 'unusable': [], 'executable_path': None,
              'executable_sha256': None, 'exit_status': None,
              'probed_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    declared = document['capabilities']
    if document['transport_kind'] not in CLI_KINDS:
        record['capabilities_confirmed'] = {k: declared[k] for k in BOOLEAN_CAPABILITIES}
    else:
        env, _ = child_environment(document, environment)
        path, sha = resolve_executable(document, environment, executable)
        if not path:
            record['unusable'] = ['launcher:' + document['launcher']]
        else:
            check_executable_location(path, rundir=rundir, project_root=project_root)
            record.update(executable_path=path, executable_sha256=sha)

            def run(argv):
                try:
                    done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env,
                                          stdin=subprocess.DEVNULL)
                except (OSError, subprocess.SubprocessError):
                    return None, None
                return done.returncode, (done.stdout or '') + (done.stderr or '')
            version_status, version = run([path, '--version'])
            if version_status == 0 and version and version.strip():
                record['cli_version'] = version.strip().splitlines()[0][:200]
            else:
                record['unusable'].append('version:exit' if version_status else 'version:unreadable')
            help_status, help_text = run(_help_command(document, path))
            record['exit_status'] = help_status
            if help_status != 0:
                help_text = ''
            record['help_sha256'] = hashlib.sha256(help_text.encode()).hexdigest() if help_text else None
            for flag in template_flags(document):
                record['flags'][flag] = 'confirmed' if help_text and _flag_present(flag, help_text) else 'missing'
            record['unusable'] += sorted(f for f, state in record['flags'].items() if state != 'confirmed')
            if not help_text:
                record['unusable'].append('help:exit' if help_status else 'help:unreadable')
        usable = not record['unusable']
        carried = {'structured_output': any(_carrier_confirmed(document, p, record['flags'])
                                            for p in ('schema', 'schema_file')),
                   'effort_control': any(_carrier_confirmed(document, name, record['flags'])
                                         for name in ('effort', 'effort_config'))}
        record['capabilities_confirmed'] = {
            k: bool(declared[k] and usable and carried.get(k, k in ('session_id', 'usage_report')))
            for k in BOOLEAN_CAPABILITIES}
    if write:
        target = probe_path(transport_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
    return record


def probe_problem(record, document):
    """Why a stored probe record cannot stand for this declaration (None when it can)."""
    if type(record) is not dict or set(record) != PROBE_KEYS or record.get('kind') != 'transport-probe' \
            or record.get('schema_version') != 1:
        return 'probe:shape'
    if record['transport_id'] != document['id'] or record['declaration_sha256'] != declaration_sha256(document):
        return 'probe'
    flags, confirmed, unusable = record['flags'], record['capabilities_confirmed'], record['unusable']
    if type(flags) is not dict or any(type(k) is not str or v not in ('confirmed', 'missing') for k, v in flags.items()):
        return 'probe:shape'
    if type(confirmed) is not dict or set(confirmed) - set(BOOLEAN_CAPABILITIES) \
            or any(type(v) is not bool for v in confirmed.values()):
        return 'probe:shape'
    if type(unusable) is not list or any(type(u) is not str for u in unusable):
        return 'probe:shape'
    if document['transport_kind'] in CLI_KINDS:
        sha = record['executable_sha256']
        if type(sha) is not str or not re.fullmatch(r'[0-9a-f]{64}', sha) or type(record['executable_path']) is not str:
            return 'probe:executable'
        if record['exit_status'] != 0 or set(flags) != set(template_flags(document)):
            return 'probe:shape' if set(flags) != set(template_flags(document)) else 'probe:help'
    return None


def read_probe(transport_id):
    path = probe_path(transport_id)
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
    except ValueError:
        return None
    if type(record) is not dict or record.get('kind') != 'transport-probe' or set(record) != PROBE_KEYS:
        return None
    return record


def qualification_path(transport_id):
    return state_dir() / f'{transport_id}.qualification.json'


def read_qualification(document, probe_record):
    """The stored live qualification record for this declaration and probe, or None.

    ``ravel transport qualify`` writes it after a live conformance run. It counts only while
    the declaration digest, the probe record's digest and the probed executable's sha256
    are the ones it was written for; any other record is ignored.
    """
    if probe_record is None or document['transport_kind'] not in CLI_KINDS:
        return None
    path = qualification_path(document['id'])
    try:
        record = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if (type(record) is not dict or set(record) != QUALIFICATION_RECORD_KEYS
            or record['kind'] != 'transport-qualification' or record['schema_version'] != 1
            or record['status'] != 'live_qualified' or record['transport_id'] != document['id']
            or record['declaration_sha256'] != declaration_sha256(document)
            or record['probe_sha256'] != digest(probe_record)
            or record['executable_sha256'] != probe_record.get('executable_sha256')):
        return None
    return record


def qualification_status(document, probe_record=None):
    """The declaration's status, raised to ``live_qualified`` by a matching stored qualification record."""
    status = document['qualification']['status']
    if status != 'live_qualified' and read_qualification(document, probe_record) is not None:
        return 'live_qualified'
    return status


def _qualification_pending(document, probe_record):
    """True when a shipped sandbox worker would be blind-capable once live-qualified."""
    declared = document['capabilities']
    return (document['transport_kind'] == 'cli-worker' and declared['isolation'] in SANDBOX_ISOLATION
            and declared['blind_capable'] and origin(document) == 'builtin' and sandbox_available()
            and qualification_status(document, probe_record) != 'live_qualified')


def effective_capabilities(document, probe_record, *, executable_sha256=None):
    """Declared AND confirmed AND permitted by origin and implementation. Returns (capabilities, reasons).

    ``executable_sha256``, when given, must equal the probed executable's digest.
    """
    capabilities = dict(document['capabilities'])
    if document['id'] in UNIMPLEMENTED_ROUTES:
        return None, ['unimplemented:' + document['id']]
    problem = executor_problem(document)
    if problem:
        return None, [problem]
    if document['transport_kind'] in CLI_KINDS:
        if probe_record is None:
            return None, ['probe']
        problem = probe_problem(probe_record, document)
        if problem:
            return None, [problem]
        if probe_record['unusable']:
            return None, ['probe:' + f for f in probe_record['unusable']]
        if executable_sha256 is not None and probe_record['executable_sha256'] != executable_sha256:
            return None, ['probe:stale-executable']
        confirmed = probe_record['capabilities_confirmed']
        for key in BOOLEAN_CAPABILITIES:
            capabilities[key] = bool(capabilities[key] and confirmed.get(key))
    builtin = origin(document) == 'builtin'
    qualified = qualification_status(document, probe_record) == 'live_qualified'
    if document['transport_kind'] != 'http-model' and capabilities['isolation'] in SANDBOX_ISOLATION \
            and not (builtin and qualified and sandbox_available()):
        capabilities['isolation'] = 'cli-policy'
    if not builtin:
        if _rank(capabilities['isolation'], ISOLATION) > _rank('cli-policy', ISOLATION):
            capabilities['isolation'] = 'cli-policy'
        capabilities['blind_capable'] = False
    return capabilities, []


# ------------------------------------------------------------ selection

def _rank(value, order):
    return order.index(value)


VOTING = ('critic', 'verifier', 'plan-critic', 'plan_critic', 'physics_critic', 'reviewer')


def is_voting(card):
    """Canonical independence kind, with legacy fallback only when it is absent."""
    if "independence" in card:
        return (card["independence"] or {}).get("kind") == "voting"
    return card.get('voting') is True or bool((card.get('requires') or {}).get('blind')) \
        or str(card.get('id', '')).split('.')[-1] in VOTING


def unmet(document, capabilities, card, probe_record=None):
    """The requirement names a transport fails for a role card (empty when it qualifies).

    A voting role runs with the route's full tools; its independence comes from isolation.
    On a CLI or host route it needs a sandbox-isolated worker, so a one-shot under the CLI's
    own tool policy is refused with ``isolation``. A shipped sandbox worker that lacks only
    its live qualification is refused with ``qualification`` rather than ``blind``.
    """
    requires = card.get('requires') or {}
    model = card.get('model') or {}
    voting = is_voting(card)
    pending = _qualification_pending(document, probe_record)
    missing = []
    if 'tools' in requires and _rank(capabilities['tools'], TOOLS) < _rank(requires['tools'], TOOLS):
        missing.append('tools')
    if voting and document['transport_kind'] in CLI_KINDS + ('host-subagent',) \
            and capabilities['isolation'] not in SANDBOX_ISOLATION:
        missing.append('qualification' if pending else 'isolation')
    if requires.get('structured_output') and not capabilities['structured_output']:
        missing.append('structured_output')
    if 'isolation_min' in requires and _rank(capabilities['isolation'], ISOLATION) < _rank(requires['isolation_min'], ISOLATION):
        missing.append('isolation')
    if 'attestation_min' in requires and _rank(capabilities['attestation'], ATTESTATION) < _rank(requires['attestation_min'], ATTESTATION):
        missing.append('attestation')
    if requires.get('blind') and not blind_admissible(document, capabilities):
        missing.append('qualification' if pending else 'blind')
    if voting and qualification_status(document, probe_record) == 'declared':
        missing.append('qualification')
    tier = model.get('tier')
    if tier and not any(tier in m['tiers'] for m in document['models']):
        missing.append('tier:' + tier)
    return list(dict.fromkeys(missing))


def blind_admissible(document, capabilities=None):
    """Blind roles: stateless HTTP, the RAVEL loop or a relay, or a CLI isolated to its workspace.

    Without ``capabilities`` the declaration is judged by its effective capabilities as though
    probed, so a declared-only sandbox or a user-path declaration never qualifies.
    """
    if capabilities is None:
        capabilities = dict(document['capabilities'])
        if document['id'] in UNIMPLEMENTED_ROUTES or not executor_available(document):
            return False
        builtin = origin(document) == 'builtin'
        if not builtin:
            return False
        if document['transport_kind'] != 'http-model' and capabilities['isolation'] in SANDBOX_ISOLATION \
                and not (document['qualification']['status'] == 'live_qualified' and sandbox_available()):
            return False
    if not capabilities['blind_capable']:
        return False
    if document['transport_kind'] in ('http-model', 'external-relay'):
        return True
    return capabilities['isolation'] in SANDBOX_ISOLATION


def _model_for(document, tier, preferences):
    chosen = ((preferences.get('tier_models') or {}).get(tier) or {}).get(document['id'])
    if chosen:
        return chosen
    for model in document['models']:
        if tier in model['tiers'] and '{' not in model['id']:
            return model['id']
    return None


def _local_problem(document, model, local_models):
    if local_models is None:
        return None
    if document['transport_kind'] in CLI_KINDS + ('host-subagent',):
        return 'local_only:no-verified-destination'
    if document['billing'] != 'local':
        return 'local_only'
    endpoint = document.get('endpoint')
    if endpoint is None or not is_loopback(endpoint):
        return 'local_only'
    if model.lower().endswith(':cloud') or '-cloud' in model.lower():
        return 'local_only:cloud-model'
    if model not in local_models:
        return 'local_models'
    return None


def select(card, preferences, *, probes=None, assigned=None, local_models=None, executables=None):
    """The first preferred transport that meets the card; TransportRefusal names what is missing.

    ``probes`` maps transport ids to probe records (default: the stored records).
    ``assigned`` maps role ids to earlier selections, for ``distinct_family_from``; a named role
    that has no assignment yet refuses, as does a family that cannot be determined.
    ``local_models`` (a list) restricts selection to loopback, locally billed HTTP routes serving those
    models; CLI routes have no verified local destination and are refused.
    ``executables`` maps transport ids to the sha256 of the executable that will run (default: the
    launcher on PATH now); a probe of another executable is stale.
    An effort the card asks for that the transport cannot carry refuses with ``effort``.
    """
    if type(preferences) is not dict or preferences.get('kind') != 'agent-preferences' or preferences.get('schema_version') != 1:
        raise TransportRefusal('run preferences must be an agent-preferences record, schema_version 1', ['preferences'])
    family = card.get('family')
    order = (preferences.get('families') or {}).get(family)
    if not order:
        raise TransportRefusal(f'no transport preference list for role family {family!r}', ['preferences:' + str(family)])
    model_spec = card.get('model') or {}
    tier, effort = model_spec.get('tier'), model_spec.get('effort')
    bindings = preferences.get('model_families') or {}
    avoid, missing = {}, []
    for role in model_spec.get('distinct_family_from') or []:
        other = (assigned or {}).get(role)
        if other is None:
            missing.append(f'distinct_family_from:{role}:unassigned')
            continue
        avoid[role] = other.get('family') or family_of(load(other['transport_id']), other['model'], bindings)
        if avoid[role] == 'unknown':
            missing.append(f'distinct_family_from:{role}:unknown-family')
    if missing:
        raise TransportRefusal(f'role {card.get("id")!r} cannot check model-family diversity: ' + ', '.join(missing),
                               missing)
    tried = []
    for transport_id in order:
        try:
            document = load(transport_id)
        except KeyError:
            tried.append(f'{transport_id}: undeclared')
            missing.append('declaration:' + transport_id)
            continue
        record = (probes or {}).get(transport_id) if probes is not None else read_probe(transport_id)
        sha = None
        if document['transport_kind'] in CLI_KINDS:
            sha = (executables or {}).get(transport_id) if executables is not None else resolve_executable(document)[1]
        capabilities, reasons = effective_capabilities(document, record, executable_sha256=sha)
        if capabilities is not None:
            reasons = unmet(document, capabilities, card, record)
            if effort is not None and not capabilities['effort_control']:
                reasons.append('effort')
        model = _model_for(document, tier, preferences) if not reasons else None
        if not reasons and model is None:
            reasons = ['model:' + str(tier)]
        if not reasons:
            problem = model_problem(document, model, bindings)
            if problem:
                reasons = [problem]
        if not reasons:
            local = _local_problem(document, model, local_models)
            if local:
                reasons = [local]
        if not reasons:
            chosen_family = family_of(document, model, bindings)
            if avoid and chosen_family == 'unknown':
                reasons = ['distinct_family_from:unknown-family']
            clashes = [r for r, f in avoid.items() if f == chosen_family]
            if clashes:
                reasons = ['distinct_family_from:' + r for r in clashes]
        if reasons:
            tried.append(f'{transport_id}: ' + ', '.join(reasons))
            missing.extend(r for r in reasons if r not in missing)
            continue
        return {'transport_id': transport_id, 'model': model, 'family': family_of(document, model, bindings),
                'effort': effort, 'declaration_sha256': declaration_sha256(document),
                'declaration_origin': origin(document),
                'probe_sha256': digest(record) if document['transport_kind'] in CLI_KINDS else None}
    raise TransportRefusal(f'no preferred transport meets role {card.get("id")!r}: ' + '; '.join(tried), missing)


def check_distinct_families(card, observed):
    """Receipt-time check: ``observed`` maps role ids to the observed model ids, including this card's role.

    A missing role, or a family that cannot be read from a model id, refuses.
    """
    required = (card.get('model') or {}).get('distinct_family_from') or []
    if not required:
        return
    missing = [r for r in [card.get('id'), *required] if not observed.get(r)]
    if missing:
        raise TransportRefusal(f'role {card.get("id")!r} has no observed model for ' + ', '.join(map(str, missing)),
                               ['distinct_family_from:' + str(r) + ':unobserved' for r in missing])
    mine = model_family(observed[card['id']])
    unknown = [r for r in [card['id'], *required] if model_family(observed[r]) == 'unknown']
    if unknown:
        raise TransportRefusal(f'role {card.get("id")!r}: model family unknown for ' + ', '.join(unknown),
                               ['distinct_family_from:' + r + ':unknown-family' for r in unknown])
    clashes = [role for role in required if model_family(observed[role]) == mine]
    if clashes:
        raise TransportRefusal(f'role {card.get("id")!r} shares model family {mine!r} with ' + ', '.join(clashes),
                               ['distinct_family_from:' + r for r in clashes])


# ------------------------------------------------------------ model classes

def model_classes():
    document = json.loads(MODEL_CLASSES.read_text(encoding='utf-8'))
    if document.get('kind') != 'transport-model-classes' or document.get('schema_version') != 1:
        raise ValueError('model-classes index has an unknown kind or schema_version')
    return document['classes']


def routes(class_id):
    for row in model_classes():
        if row['id'] == class_id:
            return {'worker': list(row['worker']), 'judgment': list(row['judgment'])}
    raise KeyError(class_id)


# ------------------------------------------------------------ command line

def _row(document):
    record = read_probe(document['id'])
    if document['transport_kind'] not in CLI_KINDS:
        probed = 'n/a'
    elif record is None or probe_problem(record, document):
        probed = 'unprobed'
    else:
        probed = 'unusable' if record.get('unusable') else 'confirmed'
    return {'id': document['id'], 'transport_kind': document['transport_kind'], 'billing': document['billing'],
            'auth': document['auth']['kind'], 'families': sorted({m['family'] for m in document['models']}),
            'qualification': document['qualification']['status'], 'origin': origin(document), 'probe': probed}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='ravel transport', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    listing = commands.add_parser('list', help='list declared transports with their probe state')
    listing.add_argument('--json', action='store_true')
    show = commands.add_parser('show', help='print one declaration and its stored probe record')
    show.add_argument('transport_id')
    check = commands.add_parser('probe', help="read a CLI's version and --help and confirm its template flags")
    check.add_argument('transport_id', nargs='?')
    check.add_argument('--all', action='store_true', help='probe every CLI transport whose launcher is installed')
    check.add_argument('--executable', help='probe this executable instead of the launcher on PATH')
    commands.add_parser('qualify', add_help=False,
                        help='run the live conformance task on a CLI worker and write its qualification record')
    if list(sys.argv[1:] if argv is None else argv)[:1] == ['qualify']:
        from .transports.cli_worker import main as qualify
        return qualify(list(sys.argv[1:] if argv is None else argv)[1:])
    args = parser.parse_args(argv)
    try:
        if args.command == 'list':
            rows = [_row(d) for d in all_declarations()]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                print(f'{"id":34} {"kind":15} {"billing":13} {"auth":8} {"probe":10} qualification')
                for row in rows:
                    print(f'{row["id"]:34} {row["transport_kind"]:15} {row["billing"]:13} {row["auth"]:8} '
                          f'{row["probe"]:10} {row["qualification"]}')
            return 0
        if args.command == 'show':
            document = load(args.transport_id)
            print(json.dumps({'declaration': document, 'declaration_sha256': declaration_sha256(document),
                              'probe': read_probe(args.transport_id)}, indent=2, sort_keys=True))
            return 0
        if args.all:
            ids = [d['id'] for d in all_declarations() if d['transport_kind'] in CLI_KINDS and shutil.which(d['launcher'])]
        elif args.transport_id:
            ids = [args.transport_id]
        else:
            parser.error('name a transport or pass --all')
        results = [probe(i, executable=args.executable if not args.all else None) for i in ids]
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0 if all(not r['unusable'] for r in results) else 3
    except (KeyError, ValueError, OSError) as exc:
        parser.exit(1, f'transport: {exc}\n')


if __name__ == '__main__':
    sys.exit(main())
