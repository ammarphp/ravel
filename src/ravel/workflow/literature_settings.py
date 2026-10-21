"""Trusted installation settings for governed literature serving.

The only source of a production ``literature_serving.Serving``: one installation
settings document, read by the supervisor process that owns the broker. Nothing
in it comes from a run, a role card or a worker request. Absent settings,
``provider = "off"`` and ``provider = "auto"`` without a registered index keep
today's behaviour (no configuration; every literature call is a receipted
``retrieval_unavailable``). An explicitly selected or registered index that is
missing, corrupt, unqualified or mismatched becomes a
``literature_serving.ConfigurationRefusal``: each literature call is then a
receipted ``provider_unqualified`` or ``stale_index`` refusal, never a silent
change of engine.

Settings (JSON, closed)::

    {"schema_version": 1, "kind": "ravel-retrieval-settings",
     "retrieval": {"provider": "auto" | "off" | "local", "graph": false,
                   "index_root": <abs dir>, "index_manifest_sha256": <hex> | null,
                   "source_root": <abs dir>, "qualification": <abs file>,
                   "cursor_key": <abs file>, "models_root": <abs dir> | null,
                   "budgets": {...} | null, "ceilings": {...} | null, "allowance": {...} | null,
                   "excluded_roots": [<abs dir>, ...],
                   "excluded_origins": [{"kind": "document" | "pin" | "run" | "path", "value": ...}, ...]
                                       | <abs path of an evaluator-supplied excluded-origins document>}}

An excluded-origin document is ``{"schema_version": 1, "kind": "literature-excluded-origins",
"origins": [...]}``. A configured set makes every build refuse a corpus descending from one of its
origins, makes serving withhold rows that do, and must equal the set the pinned index recorded.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import re

from . import broker as core, literature_build
from .literature_serving import ACTION, ConfigurationRefusal, Serving
from .state_io import read_json

SETTINGS_ENV = 'RAVEL_RETRIEVAL_SETTINGS'
SETTINGS_KIND = 'ravel-retrieval-settings'
SETTINGS_PROVIDERS = ('auto', 'off', 'local')
SETTINGS_KEYS = frozenset({'provider', 'graph', 'index_root', 'index_manifest_sha256', 'source_root',
                           'qualification', 'cursor_key', 'models_root', 'budgets', 'ceilings', 'allowance',
                           'excluded_roots', 'excluded_origins'})
ORIGINS_KIND = 'literature-excluded-origins'
_PATH_KEYS = ('index_root', 'source_root', 'qualification', 'cursor_key', 'models_root')


class SettingsError(ValueError):
    """An installation retrieval settings document outside its closed schema."""


def _json_file(path):
    path = core.ordinary(path)
    if not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError(str(path) + ' is not an ordinary bounded file')
    return read_json(path)


def settings_path():
    """``$RAVEL_RETRIEVAL_SETTINGS``, else ``retrieval/settings.json`` in the per-user shared data directory."""
    override = os.environ.get(SETTINGS_ENV)
    if override:
        return Path(override).expanduser()
    from ravel.paths import shared_native_build
    return shared_native_build() / 'retrieval' / 'settings.json'


def validate_settings(document):
    """The closed settings document; returns its ``retrieval`` section with defaults filled."""
    if (not isinstance(document, dict) or set(document) != {'schema_version', 'kind', 'retrieval'}
            or type(document['schema_version']) is not int or document['schema_version'] != 1
            or document['kind'] != SETTINGS_KIND or not isinstance(document['retrieval'], dict)):
        raise SettingsError('retrieval settings must be {schema_version: 1, kind, retrieval}')
    section = document['retrieval']
    unknown = set(section) - SETTINGS_KEYS
    if unknown:
        raise SettingsError('unknown retrieval settings: ' + ', '.join(sorted(unknown)))
    result = {'provider': 'auto', 'graph': False, 'index_manifest_sha256': None, 'budgets': None,
              'ceilings': None, 'allowance': None, 'excluded_roots': [], 'excluded_origins': [],
              **{key: None for key in _PATH_KEYS},
              **deepcopy(section)}
    if result['provider'] not in SETTINGS_PROVIDERS:
        raise SettingsError('retrieval.provider must be one of ' + ', '.join(SETTINGS_PROVIDERS))
    if result['graph'] is not False:
        # Graph-guided retrieval stays off until its own profile is qualified.
        raise SettingsError('retrieval.graph must be false')
    pin = result['index_manifest_sha256']
    if pin is not None and (not isinstance(pin, str) or re.fullmatch(r'[0-9a-f]{64}', pin) is None):
        raise SettingsError('retrieval.index_manifest_sha256 must be a sha256 hex digest or null')
    for key in _PATH_KEYS:
        value = result[key]
        if value is not None and (not isinstance(value, str) or not Path(value).is_absolute()):
            raise SettingsError('retrieval.' + key + ' must be an absolute path or null')
    for key in ('budgets', 'ceilings', 'allowance'):
        if result[key] is not None and not isinstance(result[key], dict):
            raise SettingsError('retrieval.' + key + ' must be an object or null')
    # Roots no corpus member, product or index may lie under (read by the index build driver).
    excluded = result['excluded_roots']
    if (not isinstance(excluded, list) or len(excluded) > 256 or len(set(map(str, excluded))) != len(excluded)
            or any(not isinstance(root, str) or not root or not Path(root).is_absolute() for root in excluded)):
        raise SettingsError('retrieval.excluded_roots must be a list of distinct absolute paths')
    for key in ('index_root', 'source_root'):
        if result[key] is not None and any(Path(result[key]) == Path(root) or Path(root) in Path(result[key]).parents
                                           for root in excluded):
            raise SettingsError('retrieval.' + key + ' lies under an excluded root')
    origins = result['excluded_origins']
    if isinstance(origins, str):
        if not Path(origins).is_absolute():
            raise SettingsError('retrieval.excluded_origins names a document by absolute path')
    else:
        from .literature_index import normalize_excluded_origins
        try:
            normalize_excluded_origins(origins)
        except ValueError as exc:
            raise SettingsError('retrieval.excluded_origins: ' + str(exc)) from None
    if result['provider'] == 'local':
        missing = [k for k in ('index_root', 'index_manifest_sha256', 'source_root', 'qualification', 'cursor_key')
                   if result[k] is None]
        if missing:
            raise SettingsError('retrieval.provider local requires ' + ', '.join(missing))
    return result


def _local_provider(snapshot, *, cursor_key, models_root):
    """The local hybrid provider over the pinned models, through the index adapters the build uses.

    ``literature_models.index_models`` binds model, tokenizer, runtime and qualification into
    one identity, so the loader and the index builder agree; an index built with other models,
    another runtime or another qualification is refused by the provider's identity check.
    """
    from . import literature_index, literature_models
    root = None if models_root is None else Path(models_root)
    embedder = literature_models.Embedder(root=root)
    reranker = literature_models.Reranker(root=root)
    index_embedder, index_reranker = literature_models.index_models(
        embedder, reranker, embedding_qualification=literature_models.qualify(embedder),
        reranker_qualification=literature_models.qualify(reranker))
    return literature_index.HybridLiteratureProvider(snapshot, embedder=index_embedder, reranker=index_reranker,
                                                     cursor_key=cursor_key)


def _registered(settings):
    """Whether ``auto`` finds a registered local index: a configured root with a current pointer or a pin."""
    root = settings['index_root']
    if root is None:
        return False
    return settings['index_manifest_sha256'] is not None or os.path.lexists(os.path.join(root, 'current.json'))


def excluded_origins(section):
    """The normalized excluded-origin set of a validated settings section (reads its document if named)."""
    from .literature_index import normalize_excluded_origins
    value = section.get('excluded_origins') or []
    if isinstance(value, str):
        document = _json_file(value)
        if (not isinstance(document, dict) or set(document) != {'schema_version', 'kind', 'origins'}
                or document['schema_version'] != 1 or document['kind'] != ORIGINS_KIND):
            raise SettingsError('the excluded-origins document must be {schema_version: 1, kind, origins}')
        value = document['origins']
    return normalize_excluded_origins(value)


def configured_excluded_origins():
    """Trusted installation policy for consumers outside retrieval; never read withheld sources."""
    path = settings_path()
    if not os.path.lexists(path) and not os.environ.get(SETTINGS_ENV):
        return ()
    return excluded_origins(validate_settings(_json_file(path)))


def from_settings(path=None):
    """Trusted loader: ``Serving``, a ``ConfigurationRefusal``, or None for today's behaviour.

    Reads one installation settings document (``settings_path()`` by default).
    No setting is taken from a run, a role card or a worker request. A missing
    document, ``provider = "off"`` and ``provider = "auto"`` without a registered
    index return None. An explicitly selected or registered index that is missing,
    corrupt, unqualified or mismatched is diagnosed, never replaced.
    """
    path = settings_path() if path is None else Path(path)
    if not os.path.lexists(path):
        return None
    try:
        settings = validate_settings(_json_file(path))
    except (OSError, ValueError) as exc:
        return ConfigurationRefusal('provider_unqualified', 'retrieval settings unusable: ' + str(exc))
    if settings['provider'] == 'off' or (settings['provider'] == 'auto' and not _registered(settings)):
        return None
    for key in ('source_root', 'qualification', 'cursor_key'):
        if settings[key] is None:
            return ConfigurationRefusal('provider_unqualified', 'registered index without retrieval.' + key)
    try:
        origins = excluded_origins(settings)
    except (OSError, ValueError) as exc:
        return ConfigurationRefusal('provider_unqualified', 'excluded origins unusable: ' + str(exc))
    try:
        snapshot = literature_build.load_index(settings['index_root'], settings['index_manifest_sha256'])
    except (OSError, ValueError) as exc:
        return ConfigurationRefusal('stale_index', 'pinned literature index unavailable: ' + str(exc))
    from .literature_index import excluded_origins_sha256
    if snapshot['manifest'].get('excluded_origins_sha256') != excluded_origins_sha256(origins):
        return ConfigurationRefusal('stale_index', 'the pinned index was built under another excluded-origin set')
    try:
        qualification = _json_file(settings['qualification'])
    except (OSError, ValueError) as exc:
        return ConfigurationRefusal('provider_unqualified', 'qualification record unavailable: ' + str(exc))
    try:
        key_path = core.ordinary(settings['cursor_key'])
        if not key_path.is_file() or not 32 <= key_path.stat().st_size <= 4096:
            raise ValueError('cursor key must be an ordinary file of 32 to 4096 bytes')
        cursor_key = key_path.read_bytes()
        provider = _local_provider(snapshot, cursor_key=cursor_key, models_root=settings['models_root'])
    except Exception as exc:  # any failure to load the selected provider is diagnosed, never replaced
        return ConfigurationRefusal('provider_unqualified', 'local provider unavailable: '
                                    + type(exc).__name__ + ': ' + str(exc))
    try:
        return Serving(provider, snapshot=snapshot, qualification=qualification,
                       source_root=settings['source_root'], index_root=settings['index_root'],
                       budgets=settings['budgets'], ceilings=settings['ceilings'], allowance=settings['allowance'],
                       excluded_origins=origins)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return ConfigurationRefusal('provider_unqualified', 'retrieval settings rejected: ' + str(exc))


def for_tools(tools, path=None):
    """The configuration a production broker binds: loaded only for a toolbelt with a literature tool."""
    if not any(tool['executes_through']['action'] == ACTION for tool in tools):
        return None
    return from_settings(path)
