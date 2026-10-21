"""The toolbelt: typed tools for one role card, generated from the atlas.

``for_card(card, node_facts)`` returns the tools a worker sees on every transport: the
in-graph loop binds them, the broker MCP face lists them and the broker's guard
(``tool_gate``) refuses any call outside them. Each tool carries its interface row
plus ``executes_through``, the broker action and fixed arguments it resolves to.

Selection follows the card. ``tools.ravel_actions`` decides which families exist,
``knowledge.may_query`` narrows the knowledge family, ``must_check`` and
``tools.validators`` name the checks, and the work order (``node_facts``) can only
narrow them further. A family enters the toolbelt only when a registered broker action
executes it (``EXECUTABLE_ACTIONS``); every other affordance is an ``absent`` census row
naming its owner, so no tool is offered that the broker would refuse as unregistered.
At most ``MAX_TOOLS`` tools form the working set; the rest are listed by atlas id in the
omission census and stay reachable through ``knowledge_find``.

Names follow the provider function-name rule ``[A-Za-z0-9_-]{1,64}``: the design's
dotted family names (``knowledge.find``) are rendered with ``_``. Selection never
authorizes compute, and a tool description is generated text, never authority.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import sys

from ravel.paths import package_data_path

SCHEMA_VERSION = 1
MAX_TOOLS = 32
NAME = re.compile(r'[A-Za-z0-9_-]{1,64}\Z')
CENSUS = 'agents/affordances.json'
# Broker actions with a registered handler: the broker's own workspace actions and the
# handlers ``register_actions`` installs. Other owners extend this when they register one.
EXECUTABLE_ACTIONS = ('read', 'write', 'knowledge query', 'literature query', 'review-context read')
KNOWLEDGE_ACTION = 'knowledge query'
# The one argument shape of a knowledge call, for the toolbelt and the broker handler alike:
# ``{"op": <op>, "args": {...}}``. A knowledge tool's free arguments travel under ``args``.
KNOWLEDGE_ARGS_KEY = 'args'
CHECK_ACTION = 'check run'
REVIEW_ACTION = 'review-context read'
# A call naming no toolbelt tool goes to the broker under this prefix, which no broker
# registers, so an unlisted name can never alias an allowed action (``read``, ``write``).
UNLISTED_PREFIX = 'tool:'
WORKSPACE_ATLAS_ID = 'cmd:work'
# Argument schemas of the knowledge query ops (workflow/knowledge.py).
_TEXT = {'type': 'string', 'minLength': 1}
KNOWLEDGE_ARGS = {
    'find': ({'text': _TEXT, 'kinds': {'type': 'array', 'items': _TEXT},
              'limit': {'type': 'integer', 'minimum': 0, 'maximum': 50}}, ['text']),
    'show': ({'id': _TEXT}, ['id']),
    'for_node': ({'operation': _TEXT, 'validation_tier': _TEXT}, ['operation']),
    'for_failure': ({'tool': _TEXT, 'failure_class': _TEXT}, ['tool', 'failure_class']),
    'plan_check': ({'plan': {'type': 'object'}}, ['plan']),
    'coverage': ({}, []), 'xsec': ({}, []), 'constants': ({}, []), 'conventions': ({}, []),
}
WORKSPACE_TOOLS = (
    ('ws_read', 'read', {'path': _TEXT}, ['path'], True,
     'Read one workspace file under inputs/, outputs/ or scratch/ (relative path).'),
    ('ws_write', 'write', {'path': _TEXT, 'content': {'type': 'string'}}, ['path', 'content'], False,
     'Write one text file under outputs/ or scratch/ of this worker\'s own workspace.'),
)
# Affordances with no executable path yet, and the package that owns each.
ABSENT_OWNERS = {
    'ws_list': 'broker workspace listing action',
    'ws_render': 'broker figure/page render action',
    'consult': 'nested consult graph',
    'request_evidence': 'research-board post under the critic evidence budget',
    'exec': 'broker exec in a fresh sandbox',
    CHECK_ACTION: 'broker with the validator registry (data/validators/registry.json)',
    'action': 'broker action registration',
}


class ToolbeltError(ValueError):
    """The card cannot yield a valid toolbelt."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_atlas(path=None):
    path = Path(path) if path else package_data_path('knowledge', 'atlas.json')
    value = json.loads(Path(path).read_text())
    if value.get('kind') != 'knowledge-atlas':
        raise ToolbeltError('unsupported knowledge atlas')
    return value


def _rows(atlas):
    return {row['id']: row for row in atlas['entries']}


def _name(*parts):
    raw = '_'.join(parts)
    name = re.sub(r'_+', '_', re.sub(r'[^A-Za-z0-9_-]', '_', raw)).strip('_')
    if len(name) > 64:
        name = name[:55].rstrip('_') + '_' + hashlib.sha256(raw.encode()).hexdigest()[:8]
    return name


def _object(properties, required):
    return {'type': 'object', 'properties': deepcopy(properties), 'required': list(required),
            'additionalProperties': False}


def _review_args_schema():
    paging = {'offset': {'type': 'integer', 'minimum': 0},
              'max_bytes': {'type': 'integer', 'minimum': 1, 'maximum': 65536}}
    return {'type': 'object', 'oneOf': [
        _object({'artifact_id': _TEXT, **paging}, ['artifact_id']),
        _object({'section': {'enum': ['artifacts', 'omissions']},
                 'query': {'type': 'string', 'maxLength': 256}, **paging,
                 'max_bytes': {'type': 'integer', 'minimum': 1024, 'maximum': 65536}}, []),
    ]}


def _describe(row, lead, cost_class):
    parts = [lead, f"{row.get('title', row['id'])}: {row.get('summary', '')}".strip()]
    op = row.get('op') or {}
    if op.get('use_when'):
        parts.append('Use when: ' + '; '.join(op['use_when']))
    if op.get('do_not_use_when'):
        parts.append('Do not use when: ' + '; '.join(op['do_not_use_when']))
    if op.get('validation_tier'):
        parts.append('Validation tier: ' + op['validation_tier'])
    parts.append(f'Cost class: {cost_class}. Atlas id: {row["id"]}.')
    return ' '.join(p for p in parts if p)


def _tool(name, row, *, lead, args_schema, action, fixed_args=None, derivation, read_only=True,
          cost_class='cheap', native=False, consequential=False, effects=(), args_key=None):
    if not NAME.fullmatch(name):
        raise ToolbeltError(f'tool name {name!r} breaks the provider name rule')
    return {'name': name, 'atlas_id': row['id'], 'atlas_sha256': digest(row),
            'description': _describe(row, lead, cost_class), 'args_schema': args_schema,
            'derivation': derivation, 'cost_class': cost_class, 'native': native,
            'consequential': consequential, 'effects': list(effects) or ([] if read_only else ['workspace_write']),
            'executes_through': {'action': action, 'fixed_args': dict(fixed_args or {}),
                                 **({'args_key': args_key} if args_key else {})}}


def _check_id(check):
    """A card may name a check by its module (``ravel.validation.x``); the atlas id is ``check:validation.x``."""
    if ':' not in check and check.startswith('ravel.'):
        return 'check:' + check.removeprefix('ravel.')
    return check


def output_schema(card):
    """The card's final-record schema; every one carries ``handoff`` (§21.2 item 9)."""
    path = package_data_path('roles', 'schema', 'outputs', card['output']['schema'] + '.json')
    schema = json.loads(path.read_text())
    schema.pop('$schema', None)
    if 'handoff' not in schema.get('properties', {}):
        raise ToolbeltError(f"output schema {card['output']['schema']} lacks the handoff field")
    return schema


def check_card(card):
    """Card facts a toolbelt depends on; refuses rather than downgrading a critic (§4.3)."""
    if type(card) is not dict or card.get('kind') != 'role-card' or type(card.get('id')) is not str:
        raise ToolbeltError('a registered role card is required')
    requires = card.get('requires') or {}
    budget = (card.get('stop') or {}).get('evidence_budget', 0)
    if requires.get('tools') not in ('none', 'broker-readonly', 'broker-full'):
        raise ToolbeltError(f"card {card['id']} does not declare requires.tools")
    if budget > 0 and requires['tools'] == 'none':
        raise ToolbeltError(f"card {card['id']} has evidence_budget {budget} but requires.tools none; "
                            "an evidence-buying critic needs a tool-capable route")
    return card


def build(card, node_facts=None, *, atlas=None, executable=EXECUTABLE_ACTIONS, max_tools=MAX_TOOLS):
    """The toolbelt document for one card: tools, omission census, absent rows and manifest digest."""
    check_card(card)
    atlas = load_atlas() if atlas is None else atlas
    rows = _rows(atlas)
    facts = node_facts or {}
    actions = list(card['tools']['ravel_actions'])
    executable = set(executable)
    full = card['requires']['tools'] == 'broker-full'
    tools, absent = [], []

    def missing(kind, label, atlas_id, owner_key):
        absent.append({'tool': label, 'atlas_id': atlas_id, 'family': kind, 'owner': ABSENT_OWNERS[owner_key]})

    if card['requires']['tools'] != 'none':
        work = rows.get(WORKSPACE_ATLAS_ID)
        if work is None:
            raise ToolbeltError(f'atlas has no {WORKSPACE_ATLAS_ID} row for the workspace tools')
        for name, action, properties, required, read_only, lead in WORKSPACE_TOOLS:
            if read_only or full:
                tools.append(_tool(name, work, lead=lead, args_schema=_object(properties, required), action=action,
                                   derivation='authored_script', read_only=read_only))
        for label in ('ws_list', 'ws_render'):
            missing('workspace', label, WORKSPACE_ATLAS_ID, label)
        if KNOWLEDGE_ACTION in actions:
            for op in card['knowledge']['may_query']:
                if op not in KNOWLEDGE_ARGS:
                    raise ToolbeltError(f"card {card['id']} may_query names unknown knowledge op {op!r}")
                row = rows.get('cmd:knowledge ' + op) or rows.get('cmd:knowledge')
                if row is None:
                    raise ToolbeltError('atlas has no cmd:knowledge row')
                if KNOWLEDGE_ACTION in executable:
                    tools.append(_tool(_name('knowledge', op), row, lead=f'Query the knowledge atlas ({op}).',
                                       args_schema=_object(*KNOWLEDGE_ARGS[op]), action=KNOWLEDGE_ACTION,
                                       fixed_args={'op': op}, args_key=KNOWLEDGE_ARGS_KEY,
                                       derivation='retrieval'))
                else:
                    missing('knowledge', _name('knowledge', op), row['id'], 'action')
        from . import literature_roles, literature_serving
        literature_ops = literature_roles.operations(card)
        if literature_ops:
            row = rows.get('cmd:literature')
            if row is None:
                raise ToolbeltError('atlas has no cmd:literature row')
            tools.extend(literature_roles.tools(card, row, executable=executable))
            if literature_serving.ACTION not in executable:
                for op in literature_ops:
                    missing('literature', literature_serving.TOOL_NAMES[op], row['id'], 'action')
        checks = list(dict.fromkeys(_check_id(c) for c in [*card['must_check'], *card['tools']['validators']]))
        if facts.get('must_check') is not None:
            checks = [c for c in checks if c in {_check_id(f) for f in facts['must_check']}]
        if CHECK_ACTION in actions:
            for check in checks:
                if check not in rows:
                    raise ToolbeltError(f'check {check} has no atlas row')
                name = _name('check', check.split(':', 1)[1])
                if CHECK_ACTION in executable:
                    from . import review_projection_checks
                    identity = next((row['id'] for row in review_projection_checks.allowlist()['validators']
                                     if _check_id(row['id']) == check), check)
                    if not review_projection_checks.permitted(card, identity):
                        missing('check', name, check, CHECK_ACTION)
                        continue
                    tools.append(_tool(name, rows[check], lead='Run a registered check.',
                                       args_schema=_object({'paths': {'type': 'array', 'items': _TEXT}}, []),
                                       action=CHECK_ACTION, fixed_args={'check_id': identity},
                                       derivation='registered_validator'))
                else:
                    missing('check', name, check, CHECK_ACTION)
        for action in actions:
            if action in (KNOWLEDGE_ACTION, CHECK_ACTION, 'literature query'):
                continue
            row = rows.get('cmd:' + action)
            label = _name('cmd', action)
            if row is not None and action in executable:
                schema = _review_args_schema() if action == REVIEW_ACTION else {'type': 'object'}
                tools.append(_tool(label, row, lead=f'Run the RAVEL action `{action}`.',
                                   args_schema=schema, action=action, derivation='toolchain'))
            else:
                missing('cmd', label, row['id'] if row else None, 'action')
        for consult in card['knowledge']['consult']:
            if consult['role'] != 'by_failure_class':
                missing('consult', _name('consult', consult['role']), 'role:' + consult['role'], 'consult')
        if card['tools']['exec_argv_prefixes']:
            missing('exec', 'exec', None, 'exec')
        if card['stop'].get('evidence_budget', 0) > 0:
            missing('evidence', 'request_evidence', 'role:' + card['id'], 'request_evidence')
    role_row = rows.get('role:' + card['id'])
    if role_row is None:
        raise ToolbeltError(f"atlas has no role:{card['id']} row")
    final = _tool('submit_final', role_row, lead='Submit the final record (structured output; ends the turn).',
                  args_schema=output_schema(card), action=None, derivation=None)
    final['executes_through'] = {'action': None, 'fixed_args': {}, 'structured_output': True}
    names = [t['name'] for t in tools]
    if len(names) != len(set(names)):
        raise ToolbeltError(f"card {card['id']} yields duplicate tool names")
    working, omitted = [final, *tools][:max_tools], [final, *tools][max_tools:]
    document = {'schema_version': SCHEMA_VERSION, 'kind': 'toolbelt', 'card_id': card['id'],
                'card_sha256': digest(card), 'atlas_sha256': digest(atlas), 'tools': working,
                'omitted': [{'name': t['name'], 'atlas_id': t['atlas_id'], 'reason': 'working_set',
                             'reachable_through': 'knowledge_find'} for t in omitted],
                'absent': absent}
    document['manifest_sha256'] = manifest_sha256(document)
    return document


def workspace_tools(actions, *, atlas=None):
    """The workspace tools (``ws_read``, ``ws_write``) for the broker actions named, for a worker
    launched without a card toolbelt (a trusted direct descriptor)."""
    atlas = load_atlas() if atlas is None else atlas
    work = _rows(atlas).get(WORKSPACE_ATLAS_ID)
    if work is None:
        raise ToolbeltError(f'atlas has no {WORKSPACE_ATLAS_ID} row for the workspace tools')
    return [_tool(name, work, lead=lead, args_schema=_object(properties, required), action=action,
                  derivation='authored_script', read_only=read_only)
            for name, action, properties, required, read_only, lead in WORKSPACE_TOOLS if action in set(actions)]


def for_card(card, node_facts=None, **options) -> list[dict]:
    return build(card, node_facts, **options)['tools']


def manifest_sha256(document):
    """Digest of what a worker is offered: tool rows and the omission census (the provisioning pin)."""
    return digest({'card_id': document['card_id'], 'tools': document['tools'], 'omitted': document['omitted']})


def by_name(tools):
    return {tool['name']: tool for tool in tools}


def allowed_actions(tools):
    """The broker allowlist a toolbelt needs: exactly the actions its tools execute through."""
    return sorted({t['executes_through']['action'] for t in tools if t['executes_through']['action']})


def to_request(tools, name, args, call_id):
    """A tool call as a broker request. It never raises on model input, so every call,
    malformed or not, reaches the broker and gets a receipt:

    - a name outside the toolbelt (or the structured-output tool) becomes the action
      ``tool:<name>``, which no broker registers (``not_allowlisted``);
    - a name or arguments of the wrong type are passed as they are (``invalid_call``);
    - fixed arguments are placed first, so a model value that differs from one makes the
      pair match no tool and the guard refuses it.
    """
    tool = by_name(tools).get(name) if type(name) is str else None
    if tool is None or tool['executes_through']['action'] is None:
        action = UNLISTED_PREFIX + name if type(name) is str else name
        return {'call_id': call_id, 'action': action, 'args': deepcopy(args)}
    route = tool['executes_through']
    if type(args) is not dict:
        return {'call_id': call_id, 'action': route['action'], 'args': deepcopy(args)}
    if route.get('args_key'):
        return {'call_id': call_id, 'action': route['action'],
                'args': {**deepcopy(route['fixed_args']), route['args_key']: deepcopy(args)}}
    return {'call_id': call_id, 'action': route['action'], 'args': {**deepcopy(route['fixed_args']), **deepcopy(args)}}


def match(tools, action, args):
    """The tool a broker (action, args) pair belongs to, or None (the guard refuses it)."""
    from jsonschema import Draft202012Validator
    for tool in tools:
        route = tool['executes_through']
        if route['action'] is None or route['action'] != action or type(args) is not dict:
            continue
        if any(args.get(k) != v for k, v in route['fixed_args'].items()):
            continue
        key = route.get('args_key')
        if key:
            if set(args) != {*route['fixed_args'], key} or type(args[key]) is not dict:
                continue
            rest = args[key]
        else:
            rest = {k: v for k, v in args.items() if k not in route['fixed_args']}
        if not list(Draft202012Validator(tool['args_schema']).iter_errors(rest)):
            return tool
    return None


def knowledge_ops(tools):
    """The knowledge ops a toolbelt offers: the only ops its broker serves."""
    return sorted({t['executes_through']['fixed_args']['op'] for t in tools
                   if t['executes_through']['action'] == KNOWLEDGE_ACTION})


def validate_final(card, record):
    """Validate a final record (an object, or text JSON from a ``validated_text`` transport)."""
    from jsonschema import Draft202012Validator
    if type(record) is str:
        try:
            record = json.loads(record)
        except ValueError as exc:
            return None, [f'final record is not JSON: {exc}']
    errors = [('/'.join(str(p) for p in e.absolute_path) or '$') + ': ' + e.message
              for e in Draft202012Validator(output_schema(card)).iter_errors(record)]
    return (record if not errors else None), errors


def register_review_reader(broker, packet):
    """Bind the declared read action to the dispatcher's protected packet."""
    from . import review_context
    packet = deepcopy(packet)
    def read_review(args):
        page = review_context.broker_read(packet, args)
        return {'stdout': json.dumps(page, sort_keys=True)}
    broker.register(REVIEW_ACTION, read_review, read_only=True)


def register_actions(broker, card, *, atlas_path=None, review_packet=None):
    """Install the broker handlers this module makes executable, narrowed to the card.

    The knowledge handler takes the one shape ``{op, args}`` and refuses an op outside
    the card's ``knowledge.may_query``. A card granting the literature action gets the
    governed literature handlers: on a source-bound broker the serving actions without a
    configuration, elsewhere a handler that refuses every call with a receipted
    ``retrieval_unavailable``. Neither path serves anything without trusted settings.
    """
    from . import knowledge
    _register_literature(broker, card)
    if REVIEW_ACTION in card['tools']['ravel_actions']:
        register_review_reader(broker, review_packet)
    if KNOWLEDGE_ACTION not in card['tools']['ravel_actions']:
        return
    ops = set(card['knowledge']['may_query'])

    def query(args):
        from .broker import Refusal
        if set(args) != {'op', KNOWLEDGE_ARGS_KEY} or type(args[KNOWLEDGE_ARGS_KEY]) is not dict:
            raise Refusal('invalid_args', 'knowledge requires op and args')
        if args['op'] not in ops:
            raise Refusal('not_allowlisted', f"knowledge op {args['op']!r} is outside the card")
        rest = dict(args[KNOWLEDGE_ARGS_KEY])
        if set(rest) - set(KNOWLEDGE_ARGS[args['op']][0]):
            raise Refusal('invalid_args', 'knowledge arguments are outside the op schema')
        if atlas_path is not None:
            rest['atlas_path'] = str(atlas_path)
        result = knowledge.query(args['op'], **rest)
        return {'stdout': json.dumps(result, sort_keys=True),
                'source': {'uri': 'ravel-atlas:' + result['atlas_sha256'], 'record_id': result['result_sha256']}}
    broker.register(KNOWLEDGE_ACTION, query, derivation='retrieval', read_only=True)


def _register_literature(broker, card):
    from . import knowledge_broker, literature_serving
    if literature_serving.ACTION not in card['tools']['ravel_actions'] or literature_serving.ACTION in broker.actions:
        return
    if isinstance(broker, knowledge_broker.SourceBoundBroker):
        literature_serving.register(broker)
        return

    def unavailable(args):
        from .broker import Refusal
        raise Refusal('retrieval_unavailable', literature_serving.MESSAGES['retrieval_unavailable'])
    broker.register(literature_serving.ACTION, unavailable, derivation='retrieval', read_only=True)


# ---- the affordance census (data/agents/affordances.json) ------------------------------

TYPED_TEST = 'tests/unit/test_toolbelt.py::test_typed_tools_execute_through_the_broker'


def census(*, document=None, atlas=None):
    """One row per card and affordance: typed, generic or absent (§21.2 item 12)."""
    from . import role_registry
    atlas = load_atlas() if atlas is None else atlas
    rows = []
    for card in role_registry.all_cards(document=document):
        belt = build(card, atlas=atlas)
        for tool in belt['tools']:
            route = tool['executes_through']
            source = ('card output schema' if route['action'] is None else
                      'workflow/knowledge.py query ops' if route['action'] == KNOWLEDGE_ACTION else
                      'broker workspace actions' if route['action'] in ('read', 'write') else 'none')
            typed = source != 'none'
            rows.append({'role': card['id'], 'tool': tool['name'], 'atlas_id': tool['atlas_id'],
                         'status': 'typed' if typed else 'generic', 'schema_source': source,
                         'executes_through': 'structured_output' if route['action'] is None else
                         'broker:' + route['action'], 'test': TYPED_TEST if typed else None})
        for row in belt['omitted']:
            rows.append({'role': card['id'], 'tool': row['name'], 'atlas_id': row['atlas_id'], 'status': 'generic',
                         'schema_source': 'omitted from the working set', 'executes_through': 'knowledge_find',
                         'test': None})
        for row in belt['absent']:
            rows.append({'role': card['id'], 'tool': row['tool'], 'atlas_id': row['atlas_id'], 'status': 'absent',
                         'schema_source': None, 'executes_through': None, 'test': None, 'owner': row['owner']})
    # Rows name atlas ids, not the atlas digest: an unrelated atlas regeneration leaves the census unchanged.
    return {'schema_version': SCHEMA_VERSION, 'kind': 'affordance-census', 'generator': 'ravel.workflow.toolbelt',
            'rows': rows}


def encode(value):
    return (json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + '\n').encode()


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python -m ravel.workflow.toolbelt', description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    show = sub.add_parser('show', help='print the toolbelt of one registered role')
    show.add_argument('role')
    gen = sub.add_parser('census', help='generate or check data/agents/affordances.json')
    gen.add_argument('--write', action='store_true')
    args = parser.parse_args(argv)
    if args.command == 'show':
        from . import role_registry
        sys.stdout.write(encode(build(role_registry.load(args.role))).decode())
        return 0
    path = package_data_path(*CENSUS.split('/'))
    expected = encode(census())
    if args.write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(expected)
        return 0
    if not path.is_file() or path.read_bytes() != expected:
        print('affordance census drift: run python -m ravel.workflow.toolbelt census --write', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
