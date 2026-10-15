"""Host-written transport session receipts and the attestation rule.

The process that launches an agent CLI writes the receipt: the exact argv digest, the
executable it ran, the process facts it observed and the transport declaration it
loaded. What the CLI says about itself (its session id, model, usage and configuration
events) is kept in ``cli_reported`` and is never copied into a host field.

``attestation`` is a pure function of a verified receipt:

- ``transport_attested``: a receipt written by the RAVEL launcher that verifies against
  the host's own declaration, with a current probe bound to the executable that ran, no
  user configuration, no overriding arguments, tools within the requested role policy, and a CLI-reported
  session id distinct from every other session in the graph;
- ``host_attested``: a verified launcher receipt that fails one of those conditions;
- ``self_attested``: everything else, including every relay response, claims
  printed by an arbitrary command and receipts that fail verification.

All processes run as the user, so a receipt is tamper-evident against model or agent
forgery through the transport, not proof against the user's own processes editing files.
A machine receipt is never human or physicist review.
"""
import hashlib
import json
from pathlib import Path
import re

SCHEMA_VERSION = 1
KIND = 'transport-session-receipt'
ATTESTATIONS = ('transport_attested', 'host_attested', 'self_attested')
SHA = re.compile(r'^[0-9a-f]{64}$')
RECEIPTS_DIR = 'transport-receipts'
# The exact prompt of a session, kept beside its receipt file and bound by the receipt's prompt digest.
PROMPT_SUFFIX = '.prompt.txt'
SECTIONS = {
    'schema_version', 'kind', 'writer', 'transport', 'probe', 'executable', 'invocation', 'process', 'content',
    'effort', 'configuration', 'cli_reported'}
FIELDS = {
    'writer': {'module', 'module_sha256'},
    'transport': {'id', 'transport_kind', 'declaration_sha256', 'declaration_origin', 'qualification_status',
                  'attestation_capability'},
    'probe': {'probe_sha256', 'executable_sha256', 'current'},
    'executable': {'path', 'sha256', 'cli_version'},
    'invocation': {'host_invocation_id', 'argv_sha256', 'env_names', 'home_mode', 'dotenv_paths', 'cwd',
                   'prompt_in_argv'},
    'process': {'pid', 'pgid', 'started_utc', 'finished_utc', 'exit_status', 'stdout_sha256', 'stderr_sha256',
                'stdout_bytes', 'stderr_bytes'},
    'content': {'request_sha256', 'prompt_sha256', 'value_sha256'},
    'effort': {'requested', 'transmitted'},
    'configuration': {'effective_tools', 'isolation_profile', 'config', 'override_args', 'managed_settings_sha256',
                      'user_configuration_loaded', 'basis'},
    'cli_reported': {'label', 'session_id', 'observed_model', 'all_models', 'usage', 'config_events',
                     'rollout_sha256'}}


class ReceiptError(ValueError):
    """A receipt that does not verify; it attests nothing."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha(value, label, nullable=False):
    if value is None and nullable:
        return
    if type(value) is not str or not SHA.match(value):
        raise ReceiptError(f'receipt {label} must be a sha256')


def shape(receipt):
    """Check the closed receipt shape; return it unchanged."""
    if type(receipt) is not dict or set(receipt) != SECTIONS or receipt.get('kind') != KIND \
            or receipt.get('schema_version') != SCHEMA_VERSION:
        raise ReceiptError('not a transport session receipt')
    from .cli_agent_host import prompt_receipt_fields
    extensions = prompt_receipt_fields(receipt)
    for section, keys in FIELDS.items():
        # ``provider_policy``: the run's provider-policy admission of this session.
        # ``project_instructions``: the delivery record of the run's declared project instruction document.
        # ``project_run``: the run directory the session was started for.
        allowed = (keys | ({'tools_required', 'provider_policy', 'project_instructions', 'project_run'}
                           if section == 'configuration' else set())
                   | extensions.get(section, set()))
        if type(receipt[section]) is not dict or not keys <= set(receipt[section]) <= allowed:
            raise ReceiptError(f'receipt {section} fields differ')
    if 'provider_policy' in receipt['configuration']:
        from .provider_policy import validate_admission, PolicyRefused
        try:
            validate_admission(receipt['configuration']['provider_policy'])
        except PolicyRefused as exc:
            raise ReceiptError(str(exc)) from None
    _sha(receipt['writer']['module_sha256'], 'writer digest')
    _sha(receipt['transport']['declaration_sha256'], 'declaration digest')
    _sha(receipt['probe']['probe_sha256'], 'probe digest', nullable=True)
    _sha(receipt['probe']['executable_sha256'], 'probed executable digest', nullable=True)
    _sha(receipt['executable']['sha256'], 'executable digest')
    _sha(receipt['invocation']['argv_sha256'], 'argv digest')
    for key in ('stdout_sha256', 'stderr_sha256'):
        _sha(receipt['process'][key], key)
    for key in ('request_sha256', 'prompt_sha256'):
        _sha(receipt['content'][key], key)
    _sha(receipt['content']['value_sha256'], 'value digest', nullable=True)
    _sha(receipt['configuration']['managed_settings_sha256'], 'managed settings digest', nullable=True)
    from .transport_registry import TOOLS
    if receipt['configuration'].get('tools_required', 'none') not in TOOLS:
        raise ReceiptError('receipt tools_required is invalid')
    session = receipt['cli_reported']['session_id']
    if receipt['cli_reported']['label'] != 'cli-reported' or (session is not None and (
            type(session) is not str or not session.strip() or len(session) > 256)):
        raise ReceiptError('receipt cli_reported is labelled and holds a session id or null')
    if type(receipt['configuration']['override_args']) is not list or \
            type(receipt['configuration']['user_configuration_loaded']) is not bool:
        raise ReceiptError('receipt configuration flags are malformed')
    return receipt


def verify(receipt, *, declaration, request_sha256=None, value=None, writer_sha256=None):
    """Reasons a receipt does not stand for this host's launch (empty when it verifies)."""
    from . import transport_registry
    try:
        shape(receipt)
    except ReceiptError as exc:
        return [str(exc)]
    reasons = []
    if declaration is None:
        reasons.append('host has no transport declaration')
    else:
        if receipt['transport']['id'] != declaration['id']:
            reasons.append('transport id differs from the host declaration')
        if receipt['transport']['declaration_sha256'] != transport_registry.declaration_sha256(declaration):
            reasons.append('declaration digest differs from the host declaration')
    if writer_sha256 is not None and receipt['writer']['module_sha256'] != writer_sha256:
        reasons.append('receipt writer differs from this RAVEL launcher')
    if request_sha256 is not None and receipt['content']['request_sha256'] != request_sha256:
        reasons.append('request digest differs from the request sent')
    if value is not None and receipt['content']['value_sha256'] != digest(value):
        reasons.append('value digest differs from the returned value')
    if receipt['process']['exit_status'] != 0:
        reasons.append('the CLI did not exit with status 0')
    if not receipt['probe']['current'] or receipt['probe']['executable_sha256'] != receipt['executable']['sha256']:
        reasons.append('no current probe is bound to the executable that ran')
    return reasons


def attestation(receipt, *, verification, other_session_ids=(), tools_required='none'):
    """(label, reasons): the attestation of a launcher receipt, computed from its verified fields."""
    if verification:
        return 'self_attested', list(verification)
    reasons = []
    configuration = receipt['configuration']
    if receipt['transport']['attestation_capability'] != 'transport':
        reasons.append('the transport declares attestation ' + str(receipt['transport']['attestation_capability']))
    if configuration['user_configuration_loaded']:
        reasons.append('user configuration may have been loaded')
    if configuration['override_args']:
        reasons.append('extra arguments override the isolation flags')
    from .transport_registry import TOOLS
    effective = configuration['effective_tools']
    if tools_required not in TOOLS or effective not in TOOLS or TOOLS.index(effective) > TOOLS.index(tools_required):
        reasons.append(f'the session tools {effective} exceed required tools {tools_required}')
    session = receipt['cli_reported']['session_id']
    if session is None:
        reasons.append('the CLI reported no session id')
    elif session in set(other_session_ids):
        reasons.append('the CLI session id was already used in this graph')
    return ('host_attested', reasons) if reasons else ('transport_attested', [])


def relay_attestation(response, *, declaration=None):
    """A declaration digest identifies a transport claim, never the response's author."""
    return 'self_attested', ['relay evidence does not authenticate response authorship or independent execution']


def write(root, request_id, attempt_id, record):
    """Write a receipt record create-only under ``<root>/transport-receipts``; return its pin."""
    directory = Path(root) / RECEIPTS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    name = re.sub(r'[^A-Za-z0-9._-]', '_', f'{request_id}-{attempt_id}')[:200] + '.json'
    raw = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()
    with (directory / name).open('xb') as stream:
        stream.write(raw)
    return {'path': f'{RECEIPTS_DIR}/{name}', 'sha256': sha256_bytes(raw), 'size': len(raw)}


def prompt_path(receipt_file):
    """Where the exact prompt of a session is kept: beside its receipt or session record file."""
    return Path(receipt_file).with_suffix(PROMPT_SUFFIX)


def write_prompt(receipt_file, prompt, receipt):
    """Keep a session's exact prompt beside its receipt file, create-only; return its pin.

    The text must hash to the receipt's ``content.prompt_sha256``. The receipt binds it; the
    file adds no claim of its own.
    """
    raw = prompt.encode('utf-8')
    if type(receipt) is not dict or sha256_bytes(raw) != (receipt.get('content') or {}).get('prompt_sha256'):
        raise ReceiptError('prompt differs from the receipt prompt digest')
    path = prompt_path(receipt_file)
    with path.open('xb') as stream:
        stream.write(raw)
    return {'path': str(path), 'sha256': sha256_bytes(raw), 'size': len(raw)}


def read(root, pin):
    """The receipt record a pin names, after checking its digest."""
    path = Path(root) / pin['path']
    if '..' in Path(pin['path']).parts or path.is_symlink():
        raise ReceiptError('receipt pin escapes the graph')
    raw = path.read_bytes()
    if sha256_bytes(raw) != pin['sha256']:
        raise ReceiptError('transport receipt changed')
    return json.loads(raw)


def session_ids(root, *, exclude=None):
    """CLI-reported session ids of every host-written receipt already in this graph."""
    directory = Path(root) / RECEIPTS_DIR
    found = set()
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob('*.json')):
        if exclude is not None and path.name == exclude:
            continue
        try:
            record = json.loads(path.read_text())
            session = record['launcher_receipt']['cli_reported']['session_id']
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if type(session) is str:
            found.add(session)
    return found
