"""Broker-bound literature cards, explicit citation/code following and title resolution.

No implicit network, guessed reference identity or unrecorded source reads. The
existing charged discovery/acquisition services remain the public GET producers.
"""
from __future__ import annotations

import argparse
import hashlib
from copy import deepcopy
import json
from pathlib import Path
import re

from ..validation import evidence_card as ec
from . import broker as core, knowledge_broker, role_registry


ACTION = 'literature.check'


def _call(broker, args):
    """A dispatcher-owned check action. Worker allowlists are restored after it."""
    def check(value):
        pin = value['source']
        # source_check handles quantities/identifiers; _read also checks aliases/content copies.
        broker.source_check({'source': pin})
        read = broker._read({'path': pin['path']})
        raw = read['stdout'].encode('utf-8')
        if hashlib.sha256(raw).hexdigest() != pin['sha256']:
            raise core.Refusal('source_changed', 'source differs from its prospective pin')
        try:
            checked = ec.validate(value['card'], source=raw) if 'card' in value else {
                'sha256': pin['sha256'], 'size': len(raw)}
            if 'link' in value:
                link = value['link']; start, end = ec._range(link['byte_range'], len(raw))
                if raw[start:end].decode() != link['text']:
                    raise ValueError('followed link must occur verbatim at its original byte range')
                if link['target_identity'] not in link['text']:
                    raise ValueError('target identity must occur verbatim in followed link')
                if link['kind'] == 'code' and (not re.fullmatch(r'[a-f0-9]{40}', link['commit'])
                                               or link['commit'] not in link['text']):
                    raise ValueError('code following requires a literal producing commit')
                checked['link_sha256'] = ec.digest(link)
        except ValueError as exc:
            raise core.Refusal('invalid_evidence', str(exc)) from exc
        return {'stdout': json.dumps(checked, ensure_ascii=False), 'input_paths': [pin['path']],
                'source': {'uri': 'ravel-literature:source', 'record_id': pin['sha256']}}

    if ACTION not in broker.actions:
        broker.register(ACTION, check, derivation='retrieval', read_only=True)
        broker._literature_handler = check
    elif broker.actions[ACTION][0] is not getattr(broker, '_literature_handler', None):
        raise ValueError('literature action must be registered by its trusted adapter')
    granted = ACTION in broker.allowed_actions
    broker.allowed_actions.add(ACTION)
    try:
        # Fresh consumption is intentional: cached broker replies do not re-read inputs.
        sequence = len(broker.verify_ledger()) + 1
        return broker.call({'call_id': 'lit-' + str(sequence) + '-' + ec.digest(args)[:32],
                            'action': ACTION, 'args': args})
    finally:
        if not granted:
            broker.allowed_actions.remove(ACTION)


def check_cards(cards, *, broker):
    """Re-derive every census row from permitted current originals; display five."""
    if type(cards) is not list or len(cards) > ec.MAX_CARDS:
        raise ValueError('bounded complete evidence card population required')
    ids = [ec.source_pin(card) and card['id'] for card in cards]
    if len(ids) != len(set(ids)):
        raise ValueError('unique complete evidence card IDs required')
    census, visible, eligible = [], [], []
    for card in cards:
        source = ec.source_pin(card)
        source['quantities'] = [card['quantity'].get('name')] if type(card['quantity']) is dict else []
        if card['hepdata'] is not None:
            source['hepdata'] = card['hepdata']
        reply = _call(broker, {'source': source, 'card': card})
        row = {'id': card['id'], 'status': reply['status'], 'receipt_id': reply['receipt_id']}
        if reply['status'] == 'ok':
            checked = json.loads(reply['stdout_tail'])
            row.update(status='checked', **checked)
            visible.append(deepcopy(card))
            if checked['eligible_for_anchor']:
                eligible.append(card['id'])
        else:
            row['reason'] = reply['error']['code']
        census.append(row)
    return {'schema_version': 1, 'kind': 'literature-evidence-census',
            'census': census, 'cards': visible[:ec.DISPLAY_CARDS],
            'remaining_ids': [c['id'] for c in visible[ec.DISPLAY_CARDS:]],
            'anchor_ids': eligible, 'recipe_ids': list(eligible),
            'population': len(cards), 'scope': 'Verbatim source checks only; scientific judgment remains required'}


def consume_cards(report, cards, *, broker):
    """WT-1: derive the census again instead of accepting caller-authored statuses."""
    current = check_cards(cards, broker=broker)
    def semantic(value):
        value = deepcopy(value)
        for row in value['census']:
            row.pop('receipt_id', None)
        return value
    if semantic(report) != semantic(current):
        raise ValueError('literature census differs from its current complete source derivation')
    known = {row['receipt_id']: row for row in broker.verify_ledger()}
    for row, card in zip(report['census'], cards):
        source = ec.source_pin(card)
        source['quantities'] = [card['quantity'].get('name')] if type(card['quantity']) is dict else []
        if card['hepdata'] is not None:
            source['hepdata'] = card['hepdata']
        receipt = known.get(row['receipt_id'])
        if (receipt is None or receipt['action'] != ACTION
                or receipt['args_sha256'] != core.digest({'source': source, 'card': card})
                or receipt['status'] != ('ok' if row['status'] == 'checked' else row['status'])):
            raise ValueError('literature census requires actual matching broker receipts')
    return current


def follow(sources, links, *, broker):
    """Follow a finite explicit local source graph; failures remain census rows.

    A citation edge locates the target's exact identity in its parent. A code edge
    additionally locates its producing commit. No branch/HEAD stands for a commit.
    Source paths are granted broker workspace paths, never remote fetch authority.
    """
    if type(sources) is not list or type(links) is not list or len(sources) > 32 or len(links) > 128:
        raise ValueError('finite complete source and follow populations required')
    by_id = {}
    for row in sources:
        ec._keys(row, {'id', 'path', 'sha256', 'identity'}, 'follow source')
        ec._text(row['id'], 'source ID', 96); ec._text(row['identity'], 'source identity', 2048)
        if row['id'] in by_id:
            raise ValueError('unique followed source IDs required')
        by_id[row['id']] = row
    census = []
    for source in sources:
        reply = _call(broker, {'source': {k: source[k] for k in ('path', 'sha256')}})
        census.append({'id': source['id'], 'status': reply['status'], 'receipt_id': reply['receipt_id'],
                       'reason': reply['error']['code'] if reply['error'] else None})
    edges = []
    for link in links:
        ec._keys(link, {'id', 'from', 'to', 'kind', 'byte_range', 'text', 'commit'}, 'follow link')
        if link['kind'] not in {'citation', 'code'} or link['from'] not in by_id or link['to'] not in by_id:
            raise ValueError('explicit known citation/code link endpoints required')
        if link['kind'] == 'citation' and link['commit'] is not None:
            raise ValueError('citation link cannot claim a code commit')
        parent = by_id[link['from']]
        checked_link = {**deepcopy(link), 'target_identity': by_id[link['to']]['identity']}
        reply = _call(broker, {'source': {k: parent[k] for k in ('path', 'sha256')}, 'link': checked_link})
        endpoints = [r for r in census if r['id'] in (link['from'], link['to'])]
        status = 'located' if reply['status'] == 'ok' and all(r['status'] == 'ok' for r in endpoints) else 'unresolved'
        edges.append({'id': link['id'], 'from': link['from'], 'to': link['to'], 'kind': link['kind'],
                      'status': status, 'receipt_id': reply['receipt_id'],
                      'reason': reply['error']['code'] if reply['error'] else None})
    return {'schema_version': 1, 'kind': 'literature-follow-census', 'sources': census, 'links': edges,
            'scope': 'Located references and code commits; relevance, license and producing-run validity remain unverified'}


def resolve_publication_title(title, discovery_pin, *, base_dir):
    """Resolve an inert title only against authentic explicit record-resolution custody."""
    from . import literature_discovery as discovery
    ec._text(title, 'publication title', 2048)
    product = discovery.consume(discovery_pin, base_dir=base_dir)
    result = product['result']
    resolution = result.get('resolution')
    bibliography = resolution.get('bibliography') if resolution else None
    if result['operation'] != 'record' or result['status'] != 'resolved' or bibliography is None:
        raise ValueError('publication_title requires an authentic resolved provider record')
    if bibliography['title'] != title:
        raise ValueError('publication_title differs from the explicit original title choice')
    return {'type': 'publication_title', 'title': title, 'resolution_required': False,
            'identifiers': deepcopy(bibliography['identifiers']), 'discovery': deepcopy(discovery_pin),
            'scope': 'Secondary bibliographic identity only; primary-source review remains required'}


def scout_tier():
    card = role_registry.load('literature-scout')
    if card['model']['tier'] != 'judgment':
        raise ValueError('literature scout requires judgment tier')
    return card['model']


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest='op', required=True)
    for op in ('check-cards', 'follow'):
        sub = commands.add_parser(op)
        sub.add_argument('--rundir', type=Path, required=True)
        sub.add_argument('--workspace', type=Path, required=True)
        sub.add_argument('--request', type=Path, required=True)
        sub.add_argument('--max-calls', type=int, default=80)
    title = commands.add_parser('resolve-title')
    title.add_argument('--title', required=True)
    title.add_argument('--discovery', type=Path, required=True)
    title.add_argument('--base-dir', type=Path, required=True)
    commands.add_parser('tier')
    args = ap.parse_args(argv)
    if args.op == 'tier':
        result = scout_tier()
    elif args.op == 'resolve-title':
        raw = args.discovery.read_bytes()
        result = resolve_publication_title(args.title, {'path': str(args.discovery.absolute()),
                     'sha256': hashlib.sha256(raw).hexdigest()}, base_dir=args.base_dir)
    else:
        tool = knowledge_broker.create(args.rundir, args.workspace, role='literature-scout',
              node_id='literature', attempt=1, allowed_actions=['read'], max_calls=args.max_calls)
        # Parse control input inside a receipted descriptor-safe read. The retained
        # stdout tail is a digest, so complete requests above 8 KiB are not truncated.
        loaded = {}
        def load_request(value):
            from . import literature_context
            read = tool._read(value)
            loaded['value'] = literature_context.knowledge._json(read['stdout'].encode())
            return {'stdout': ec.digest(loaded['value']), 'input_paths': [value['path']]}
        tool.register('literature.request', load_request, read_only=True)
        tool.allowed_actions.add('literature.request')
        request = tool.call({'call_id': 'request-' + str(len(tool.verify_ledger()) + 1),
                             'action': 'literature.request', 'args': {'path': str(args.request)}})
        if request['status'] != 'ok':
            print(json.dumps(request)); return 2
        data = loaded['value']
        result = check_cards(data, broker=tool) if args.op == 'check-cards' else follow(data['sources'], data['links'], broker=tool)
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    if args.op == 'check-cards' and any(row['status'] != 'checked' for row in result['census']):
        return 2
    if args.op == 'follow' and any(row['status'] != 'located' for row in result['links']):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
