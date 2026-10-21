"""Model discovery and operator-facing catalogue commands, without model calls."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import tempfile
import sys
from urllib.parse import urlsplit, urlencode
import urllib.request

from . import model_catalogue as mc, transport_registry as tr

CAVEAT = ('ESTIMATED upper bound at catalogue list prices: the projection does not split cache reads; '
          'all input tokens are priced as uncached. Subscription billing may differ; unknown prices stay unknown.')


def detection_path():
    return tr.state_dir().parent / 'models' / 'detected.json'


def _write_private(path, record):
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for parent in reversed(missing):
        parent.mkdir(mode=0o700, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, delete=False, encoding='utf-8') as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write('\n')
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _credential_names(documents):
    return {name for doc in documents for name in doc['auth']['env_names']}


def safe_model(value, names):
    """Accept only model identifiers, excluding credentials echoed by a provider."""
    return (isinstance(value, str) and tr.MODEL_ID.fullmatch(value) is not None
            and not any(os.environ.get(name) and os.environ[name] in value for name in names))


def families(document):
    return {entry['family'] for entry in document['models'] if entry['family'] != 'any'}


def _observed(document, names):
    found = set()
    def visit(value, transport=None):
        if isinstance(value, dict):
            transport = value.get('transport_id', value.get('transport', transport))
            if transport == document['id']:
                for key in ('observed_model', 'model_reported'):
                    model = value.get(key)
                    if safe_model(model, names):
                        found.add(model)
            observed = value.get('observed')
            if transport == document['id'] and isinstance(observed, dict) and safe_model(observed.get('model'), names):
                found.add(observed['model'])
            for key, child in value.items():
                if isinstance(child, (dict, list)) and key not in ('tier_models', 'models', 'requested', 'model'):
                    visit(child, transport)
        elif isinstance(value, list):
            for child in value:
                visit(child, transport)
    root = tr.state_dir()
    if root.exists():
        for path in root.rglob('*'):
            if path.suffix not in ('.json', '.jsonl') or not path.is_file():
                continue
            try:
                content = path.read_text(encoding='utf-8')
                for line in content.splitlines() if path.suffix == '.jsonl' else [content]:
                    try:
                        visit(json.loads(line))
                    except ValueError:
                        continue
            except (OSError, UnicodeError):
                continue
    return found


def _listing(document, names):
    """List provider metadata only. Never include response bodies or exception text in diagnostics."""
    endpoint = document['endpoint']
    if not tr._endpoint_ok(endpoint):
        raise ValueError('invalid endpoint')
    parts = urlsplit(endpoint)
    origin = f'{parts.scheme}://{parts.netloc}'
    style = document['auth']['header_style']
    local = tr.is_loopback(endpoint)
    path = '/v1/models'
    if local and ('/api/' in parts.path or parts.port == 11434):
        path = '/api/tags'
    elif style == 'x-goog-api-key':
        path = '/v1beta/models'
    headers = {'Accept': 'application/json'}
    key_name = next((n for n in document['auth']['env_names'] if os.environ.get(n)), None)
    if key_name:
        if style == 'bearer':
            headers['Authorization'] = 'Bearer ' + os.environ[key_name]
        elif style in ('x-api-key', 'x-goog-api-key', 'api-key'):
            headers[style] = os.environ[key_name]
    if style == 'x-api-key':
        headers['anthropic-version'] = '2023-06-01'
    found = set()
    query = {}
    seen = set()
    for _ in range(100):
        url = origin + path + ('?' + urlencode(query) if query else '')
        if url in seen:
            raise ValueError('repeated listing page')
        seen.add(url)
        request = urllib.request.Request(url, headers={'Accept': 'application/json'}, method='GET')
        for name, value in headers.items():
            # urllib does not forward these headers when following redirects.
            request.add_unredirected_header(name, value)
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.load(response)
        if not isinstance(body, dict):
            raise ValueError('invalid listing response')
        entries = body.get('data', body.get('models'))
        if not isinstance(entries, list):
            raise ValueError('missing listing rows')
        for row in entries:
            if not isinstance(row, dict):
                continue
            model = row.get('id', row.get('name', row.get('model')))
            if isinstance(model, str) and style == 'x-goog-api-key':
                model = model.removeprefix('models/')
            if safe_model(model, names):
                found.add(model)
        if body.get('nextPageToken'):
            query = {'pageToken': body['nextPageToken']}
        elif body.get('has_more') and body.get('last_id'):
            query = {'after_id': body['last_id']}
        else:
            return found
    raise ValueError('listing page limit')


def detect_models(documents=None):
    """Discover candidates; listing and declaration do not prove model reachability."""
    documents = tr.all_declarations() if documents is None else documents
    from ravel.controller.step import seats
    inventory = seats.wired_transports()
    wired = set(inventory['wired'])
    names = _credential_names(documents)
    catalogue = mc.load()
    result = {'schema_version': 1, 'kind': 'detected-models',
              'detected_utc': datetime.now(timezone.utc).isoformat(), 'transports': [],
              'governed_inventory': inventory}
    for doc in documents:
        family = next(iter(sorted(families(doc))), 'any')
        row = {'id': doc['id'], 'kind': doc['transport_kind'], 'family': family, 'status': 'ok', 'models': [], 'governed_wired': doc['id'] in wired}
        models = {}
        for entry in doc['models']:
            if '{configured}' in entry['id']:
                for model in catalogue['models']:
                    if model['family'] == entry['family']:
                        models[model['id']] = 'declared'
            elif safe_model(entry['id'], names) and mc.lookup(entry['id'], catalogue):
                models[entry['id']] = 'declared'
        for model in _observed(doc, names):
            models[model] = 'observed'
        if doc['transport_kind'] in tr.CLI_KINDS and not tr.resolve_executable(doc)[0]:
            row['status'] = 'not_installed'
        elif doc['auth']['kind'] == 'env' and not any(os.environ.get(n) for n in doc['auth']['env_names']):
            row['status'] = 'no_credential'
        elif doc.get('endpoint') and doc['transport_kind'] in ('http-model', 'ravel-loop'):
            try:
                for model in _listing(doc, names):
                    if models.get(model) != 'observed':
                        models[model] = 'listed'
            except Exception as exc:
                # An exception may contain a credential, URL, response or subprocess output.
                row.update(status='unreachable', error_class=type(exc).__name__)
        elif doc['transport_kind'] not in (*tr.CLI_KINDS, 'ravel-loop'):
            # Declarations for a host/relay alone do not prove a provider is available.
            row['status'] = 'not_installed'
        probe = tr.loop_identity(doc) if doc['transport_kind'] == 'ravel-loop' else tr.read_probe(doc['id'])
        qualification = tr.read_qualification(doc, probe)
        if qualification is not None:
            observed = qualification.get('observed', {})
            model = observed.get('model')
            requested = observed.get('requested_model')
            if (safe_model(model, names) and safe_model(requested, names)
                    and seats.model_matches(requested, model)
                    and qualification.get('steps') and all(s.get('passed') is True for s in qualification['steps'])):
                models[requested] = 'qualified'
        row['models'] = [{'id': model, 'status': status, 'catalogued': mc.lookup(model, catalogue) is not None}
                         for model, status in sorted(models.items(), key=lambda x: ({'qualified': 0, 'observed': 1, 'listed': 2, 'declared': 3}[x[1]], x[0]))]
        result['transports'].append(row)
    _write_private(detection_path(), result)
    return result


def _latest():
    path = detection_path()
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding='utf-8'))
    if record.get('schema_version') != 1 or record.get('kind') != 'detected-models':
        raise ValueError('detection record invalid; rerun `ravel models detect`')
    return record


def available_documents(record=None, preferred=None, excluded=()):
    from ravel.controller.step import seats
    wired = set(seats.wired_transports()['wired'])
    documents = [d for d in tr.all_declarations() if d['id'] in wired]
    record = _latest() if record is None else record
    if record is not None:
        ok = {r['id'] for r in record['transports'] if r['status'] == 'ok'}
        documents = [d for d in documents if d['id'] in ok]
    else:
        documents = [d for d in documents if (d['transport_kind'] not in tr.CLI_KINDS
                     or tr.resolve_executable(d)[0])]
    documents = [d for d in documents if not families(d).intersection(excluded)
                 and (preferred is None or families(d).intersection(preferred))]
    order = []
    for row in tr.model_classes():
        for transport in row['worker'] + row['judgment']:
            if transport not in order:
                order.append(transport)
    documents.sort(key=lambda d: order.index(d['id']) if d['id'] in order else len(order))
    if preferred:
        documents.sort(key=lambda d: min((preferred.index(f) for f in families(d) if f in preferred), default=len(preferred)))
    return documents, record


def preferences(preset, *, record=None, preferred=None, excluded=()):
    documents, record = available_documents(record, preferred, excluded)
    # Once listing or observation exists, catalogue expansion cannot override it.
    tiers = {tier: {} for tier in tr.TIERS}
    omitted = []
    indexed = {r['id']: r for r in record['transports']} if record else {}
    catalogue = mc.load()
    for document in documents:
        rows = indexed.get(document['id'], {}).get('models', [])
        discovered = {m['id'] for m in rows if m['status'] in ('listed', 'observed', 'qualified')}
        candidates = discovered or {m['id'] for m in rows if m['status'] == 'declared'}
        subset = {**catalogue, 'models': [m for m in catalogue['models']
                                        if not rows or m['id'] in candidates]}
        # HTTP listing success with an empty list is evidence of zero listed models.
        if document.get('endpoint') and indexed.get(document['id'], {}).get('status') == 'ok':
            subset['models'] = [m for m in subset['models'] if m['id'] in discovered]
        if discovered:
            entries = []
            for entry in document['models']:
                if entry['family'] == 'any' and '{configured}' in entry['id']:
                    entries.extend({**entry, 'family': family} for family in
                                   sorted({m['family'] for m in subset['models']}))
                else:
                    entries.append(entry)
            document = {**document, 'models': entries}
        selected, missing = mc.tier_models(preset, [document], subset)
        for tier in tr.TIERS:
            tiers[tier].update(selected[tier])
        omitted.extend(missing)
    doc = {'schema_version': 1, 'kind': 'agent-preferences',
           'transport_preference': [d['id'] for d in documents], 'tier_models': tiers}
    return doc, omitted, record


def preference_problems(doc):
    from ravel.controller.authority import operator
    problems = []
    tiers = doc.get('tier_models', {}) if isinstance(doc, dict) else None
    if not isinstance(tiers, dict) or any(t not in tr.TIERS or not isinstance(entries, dict)
                                          for t, entries in tiers.items()):
        return ['Invalid tier_models mapping; choose a preset with `ravel models preset balanced --write`.']
    for entries in tiers.values():
        for model in entries.values():
            if mc.problem(model):
                problems.append(mc.remedy(model))
    validator = getattr(operator, 'agent_preference_problems', None)
    if validator:
        problems.extend(validator(doc))
    return problems


def write_preferences(doc, cap=None):
    from ravel.controller.authority import operator
    problems = preference_problems(doc)
    if problems:
        raise ValueError('; '.join(problems))
    operator._refuse_agent('ravel operator set')
    changes = {'agent_preferences': doc}
    if cap is not None:
        if not math.isfinite(cap) or cap < 0:
            raise ValueError('spending cap must be a finite nonnegative USD amount')
        changes['budgets'] = {'cost_usd': cap}
    if operator.operator_config()['source'] == 'default':
        return operator.init(mode='physicist-in-the-loop', **changes)
    return operator.set_values(changes)


def _weights(packets, level, calibration):
    from ravel.controller.engagement import envelope
    weights = {'judgment': {'input_tokens': 0, 'output_tokens': 0},
               'agent': {'input_tokens': 0, 'output_tokens': 0}}
    if not packets:
        raise ValueError('projection has no seat categories; recalibrate before estimating')
    no_retry = {**calibration, 'high_retries': 0}
    for packet in packets:
        tier = 'agent' if packet['category'] in ('producer', 'consult') else 'judgment'
        if 'input_tokens' in packet:
            values = packet
        else:
            values = envelope.project([packet], no_retry)[level]
        for metric in weights[tier]:
            weights[tier][metric] += values[metric]
    if level == 'high' and calibration.get('high_retries') and 'packet_tokens' in packets[0]:
        packet = max(packets, key=lambda s: s['packet_tokens'])
        tier = 'agent' if packet['category'] in ('producer', 'consult') else 'judgment'
        values = envelope.project([packet], no_retry)[level]
        for metric in weights[tier]:
            weights[tier][metric] += calibration['high_retries'] * values[metric]
    return weights


def estimate(preset, route=None, *, document=None):
    from ravel.controller.engagement import envelope
    installed = envelope.installed_projection()
    doc = preferences(preset)[0] if document is None else document
    chosen = {}
    for tier in ('judgment', 'agent'):
        for transport in doc['transport_preference']:
            model = doc['tier_models'][tier].get(transport)
            if model:
                chosen[tier] = model
                break
        if tier not in chosen:
            raise ValueError(f'no selectable {tier} candidate; run `ravel setup-models`')
    calibration = envelope.data('calibration.json')
    names = [route] if route else list(installed['routes'])
    result = {'preset': preset, 'caveat': CAVEAT, 'routes': {}}
    for name in names:
        if name not in installed['routes']:
            raise ValueError(f'unknown route {name!r}; choose an installed route')
        projection = installed['routes'][name]['full']
        if projection.get('status', 'ready') != 'ready':
            raise ValueError('route projection unavailable; recalibrate before estimating')
        row = {'models': dict(chosen)}
        packets = installed.get('packets', {}).get(name, {}).get('full', [])
        for level in ('low', 'central', 'high'):
            weights = _weights(packets, level, calibration)
            costs = []
            for tier, model in chosen.items():
                usage = {'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}
                for metric in ('input_tokens', 'output_tokens'):
                    total = sum(w[metric] for w in weights.values())
                    share = weights[tier][metric] / total if total else 0
                    usage[metric] = math.ceil(projection[level][metric] * share)
                costs.append(mc.price(usage, model)['cost_usd'])
            row[level + '_usd'] = None if None in costs else math.fsum(costs)
        result['routes'][name] = row
    return result


def print_estimate(result):
    print(result['caveat'])
    for route, row in result['routes'].items():
        amounts = ', '.join(f'{level} USD {row[level + "_usd"]:.6f}' if row[level + '_usd'] is not None
                            else f'{level} USD unknown' for level in ('low', 'central', 'high'))
        print(f'{route}: {amounts}; models {json.dumps(row["models"], sort_keys=True)}')


def _proposed(model):
    family = tr.model_family(model)
    common = set(dict(tr.FAMILY_PATTERNS).get(family, ())) | {''}
    tokens = set(re.split(r'[-_./:0-9]+', model)) - common
    siblings = [r for r in mc.load()['models'] if r['family'] == family]
    scores = [(len(tokens & (set(re.split(r'[-_./:0-9]+', r['id'])) - common)), r) for r in siblings]
    best = max(scores, key=lambda pair: pair[0], default=(0, None))
    class_ = best[1]['class'] if best[0] else 'strong'
    tiers = best[1]['tiers'] if best[0] else list(tr.TIERS)
    return {'id': model, 'family': family, 'class': class_, 'tiers': tiers, 'prices_per_million': None}


def main(argv=None):
    ap = mc.parser()
    args, remaining = ap.parse_known_args(argv)
    if args.command != 'calibrate' and remaining:
        ap.error('unrecognized arguments: ' + ' '.join(remaining))
    try:
        if args.command == 'list':
            rows = [r for r in mc.summary() if args.family is None or r['family'] == args.family]
            if args.json:
                print(json.dumps(rows, indent=2))
            else:
                print('id\tfamily\tclass\ttiers\tstatus\tinput/output/cache_read USD per million\torigin')
                for row in rows:
                    print('\t'.join(str(row[k]) for k in ('id', 'family', 'class', 'tiers', 'status'))
                          + f'\t{row["input"]}/{row["output"]}/{row["cache_read"]}\t{row["origin"]}')
        elif args.command == 'show':
            row = mc.lookup(args.model)
            if row is None:
                print(mc.remedy(args.model))
                return 2
            usage = dict(zip(mc._USAGE_KEYS, (1000000, 0, 0, 1000000)))
            print(json.dumps({'row': row, 'usage': usage, 'price': mc.price(usage, args.model)}, indent=2))
        elif args.command == 'detect':
            before = mc.tier_models(args.preset, tr.all_declarations())[0] if args.preset else None
            record = detect_models()
            proposals = []
            if args.adopt:
                listed = {m['id'] for r in record['transports'] for m in r['models']
                          if m['status'] == 'listed' and not m['catalogued']}
                for model in sorted(listed):
                    row = _proposed(model)
                    proposals.append(row)
                    if not args.json:
                        print('proposed row: ' + json.dumps(row))
                    if row['family'] == 'unknown' or row['family'] not in dict(tr.FAMILY_PATTERNS):
                        if not args.json:
                            print(mc.remedy(model) + '; choose a registered family explicitly')
                        continue
                    accepted = args.yes
                    if not accepted:
                        if args.json:
                            print('proposed row: ' + json.dumps(row), file=sys.stderr)
                        print(f'adopt {model} as class {row["class"]}? [y/N] ', end='', file=sys.stderr, flush=True)
                        accepted = input().strip().lower() == 'y'
                    if accepted:
                        mc.adopt(model, family=row['family'], class_=row['class'], tiers=row['tiers'])
                for r in record['transports']:
                    for m in r['models']:
                        m['catalogued'] = mc.lookup(m['id']) is not None
                _write_private(detection_path(), record)
            changed = before != mc.tier_models(args.preset, tr.all_declarations())[0] if args.preset else None
            if args.json:
                print(json.dumps({**record, **({'proposed': proposals} if proposals else {}),
                                  **({'preset_resolution_changed': changed} if args.preset else {})}, indent=2))
            else:
                for row in record['transports']:
                    error = ': ' + row['error_class'] + '; check network/credentials; rerun `ravel models detect`' if row.get('error_class') else ''
                    if row['status'] == 'no_credential':
                        document = next(d for d in tr.all_declarations() if d['id'] == row['id'])
                        error = '; export one of ' + ', '.join(document['auth']['env_names']) + '; rerun `ravel models detect`'
                    elif row['status'] == 'not_installed':
                        document = next(d for d in tr.all_declarations() if d['id'] == row['id'])
                        error = '; install/configure ' + str(document['launcher'] or 'this transport') + '; rerun `ravel models detect`'
                    print(f'{row["id"]}: {row["status"]}{error}')
                    for model in row['models']:
                        print(f'  {model["id"]}: {model["status"]}; catalogued={model["catalogued"]}')
                if args.preset:
                    print(f'preset {args.preset} resolution changed: {str(changed).lower()}')
        elif args.command == 'preset':
            doc, omitted, record = preferences(args.name)
            note = None if record else 'No detection record exists; using declared families. Run `ravel models detect`.'
            if args.write:
                write_preferences(doc)
            print(json.dumps({'agent_preferences': doc, 'omitted': omitted, 'note': note}, indent=2))
        elif args.command == 'check':
            from ravel.controller.authority import operator
            if args.run:
                from ravel.controller.store import RunStore
                from ravel.controller.authority.mode import frozen
                if not (operator.store_root() / args.run).is_dir():
                    raise ValueError('run store absent; use an existing run id')
                doc = frozen(RunStore(args.run)).get('agent_preferences')
            else:
                doc = operator.operator_config().get('agent_preferences')
            if doc is None:
                print('No agent preferences configured; run `ravel setup-models`.')
                return 2
            problems = preference_problems(doc)
            print('\n'.join(problems) if problems else 'All selected models are catalogued.')
            return 2 if problems else 0
        elif args.command == 'estimate':
            result = estimate(args.preset, args.route)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print_estimate(result)
        else:
            try:
                from ravel.controller.engagement.recalibrate import main as calibrate
            except ModuleNotFoundError as exc:
                if exc.name != 'ravel.controller.engagement.recalibrate':
                    raise
                print('Model calibration is unavailable; install a build with `ravel models calibrate`.')
                return 2
            return calibrate(remaining)
        return 0
    except (OSError, ValueError, KeyError, EOFError) as exc:
        print(str(exc))
        return 2
