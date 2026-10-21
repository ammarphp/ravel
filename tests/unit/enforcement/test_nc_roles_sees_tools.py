"""Role rows ``sees`` and ``tools`` against the installed registry: what a card lets a worker read and call.

Both cases take their rows from the effective role registry (``nc_cases.dimension_rows``), so a role added to
the registry is covered the day it is installed. The adversaries are inert files and scripted calls.

``sees``. The run directory is fictional and carries, for every input class the screening knows, author
artefacts with a fresh canary (whole files that match the class, and the class's redactable fields inside an
otherwise permitted file), the run's source restriction and a permitted artefact. The installed projection
(``review_projection.project``) and the raw-input screen (``review_projection.raw_input_class``) are driven for
the card, and every oracle is read from outside: the bytes of the written packet (manifest included), the
packet's own list of what it carried and omitted, and the canary values. Expected classes and expected
reachability are written here from the card's declared profile and read paths; neither is computed by the
projection. A card that declares nothing forbidden is held to what its card permits.

``tools``. The adversary is a scripted worker speaking MCP to an in-process broker built over the card's
toolbelt and ``tool_gate.broker_guard`` (``nc_adversary.InProcessWorker``). It reads outside the workspace
(escape, absolute path, symlinked input, a run file outside ``read_paths``), names validators and an exec
prefix the card does not declare, and calls broker actions no tool of the card executes. The oracle is the
broker's own refusal (status and code in the verified receipt ledger) and counters read from outside: the
protected sentinel files, the canary text, nothing written to the workspace's outputs, nothing run.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from nc_adversary import InProcessWorker
from nc_cases import INSTALLED, dimension_case, dimension_rows, role_row
from nc_effects import Sentinels
from nc_mutations import Mutation, register, returns

# ------------------------------------------------------------------------------------------ sees

# Per input class, the files that belong to it. ``named`` paths are placed under every root the card can read
# (the class matches by file name or path part); ``literal`` paths are placed as written (the class matches a
# run-relative prefix).
PLANTS = {
    'lessons': {'named': ['lessons/note.txt']},
    'producer_headline': {'named': ['headline.json']},
    'withheld_sources': {'named': ['withheld/source.txt']},
    'held_out_artifacts': {'named': ['held_out/data.json']},
    'first_method': {'named': ['first_method_result.json']},
    'final_partitions': {'named': ['confirmation/part.json']},
    'evaluator_truth_columns': {'named': ['truth_columns.json']},
    'other_verdicts': {'literal': ['review/verdicts/v.json', 'agent-work/n/final.json']},
    'board_prose': {'literal': ['research/board/post.md']},
    'producer_numbers': {'literal': ['outputs/numbers.json']},
    'critic_reasoning': {'literal': ['review/critic_notes.json']},
    'claim_quantity': {'literal': ['claims/quantity.json']},
}
# The JSON fields a class withholds from a file that is otherwise permitted.
FIELDS = {
    'producer_headline': ('headline', 'producer_verdict', 'conclusion', 'result_summary'),
    'other_verdicts': ('verdict', 'votes', 'vote', 'disposition'),
    'critic_reasoning': ('rationale', 'reasoning'),
    'evaluator_truth_columns': ('truth', 'truth_columns', 'evaluator_truth'),
}
# Never projected whatever the card says: graph and review state, and live worker calls.
ALWAYS = {'framework/state.json': 'graph_or_review_state', 'graphs/g.json': 'graph_or_review_state',
          'review/packets/p.json': 'graph_or_review_state', 'inputs/calls/receipt.json': 'worker_calls'}
PLAN_AND_CONTRACT = ('inputs/request_plan.json', 'inputs/task_contract.json')
KEPT = 'kept-by-every-card'
PERMITTED = 'permitted artefact of the run'
RESTRICTION = {'kind': 'forbidden-source', 'statement': 'fictional withheld material', 'evidence': [],
               'origin': 'harness', 'paths': ['**/withheld/**']}


def _inside(path, rel):
    return rel == path or (path.endswith('/') and rel.startswith(path))


def _reachable(card, rel):
    """Whether the card's profile and read paths make run file ``rel`` a candidate of its packet."""
    sees = card['sees']
    if sees['profile'] == 'spec-denied':
        return rel in PLAN_AND_CONTRACT
    paths = card['tools']['read_paths']
    if sees['profile'] == 'blind':
        paths = [p for p in paths if p.startswith('inputs/')]
    return any(_inside(p, rel) for p in paths)


def _write(run, rel, content):
    path = run / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content if isinstance(content, bytes) else content.encode()
    path.write_bytes(data)
    return data


# Classes whose files a second class also claims (a critic's notes live under the review prefix; a claim is
# also a producer number; the first method's products are the run's outputs and claims), so a card that
# declares only the second still screens them.
ALSO = {'critic_reasoning': ('other_verdicts',), 'claim_quantity': ('producer_numbers', 'first_method'),
        'producer_numbers': ('first_method',)}


def _screen_class(card, cls):
    """The class that must keep a file of ``cls`` out of the card's packet (None when the card carries it)."""
    declared = card['sees'].get('forbidden_inputs', [])
    claimed = sorted(c for c in (cls, *ALSO.get(cls, ())) if c in declared)
    return claimed[0] if claimed else None


def _plant(nc, run, card):
    """Plant every class (and the fields, the restriction and the permitted file); return the plan.

    ``files`` maps a run-relative path to ``(class, bytes, canary)``; ``fields`` maps a fields-file path to
    the bytes written there; ``field_canary`` gives each redactable class's canary text.
    """
    roots = ['inputs/'] + [p for p in card['tools']['read_paths'] if p.endswith('/') and p != 'inputs/']
    field_canary = {c: nc.effects.canary(f'field-{c}').value for c in FIELDS}
    files = {}
    for cls, plan in PLANTS.items():
        rels = [root + name for root in roots for name in plan.get('named', ())] + list(plan.get('literal', ()))
        for rel in dict.fromkeys(rels):
            canary = nc.effects.canary(f'file-{len(files)}')
            text = json.dumps({'note': canary.value}) if rel.endswith('.json') else f'note {canary.value}\n'
            files[rel] = (cls, _write(run, rel, text), canary)
    fields = {}
    body = {'kept': KEPT, **{key: field_canary[cls] for cls, keys in FIELDS.items() for key in keys}}
    for rel in dict.fromkeys([root + 'fields.json' for root in roots] + [PLAN_AND_CONTRACT[0]]):
        fields[rel] = _write(run, rel, json.dumps(body, sort_keys=True))
    _write(run, PLAN_AND_CONTRACT[1], json.dumps({'forbidden_sources': [RESTRICTION], 'kept': KEPT}))
    permitted = {root + 'permitted.txt': _write(run, root + 'permitted.txt', PERMITTED) for root in roots}
    for rel in ALWAYS:
        _write(run, rel, json.dumps({'note': 'state'}))
    return {'files': files, 'fields': fields, 'permitted': permitted, 'field_canary': field_canary}


def _raw_expectation(card, rel, cls):
    """The class the raw-input screen must name for ``rel`` (None when the card carries the file)."""
    sees = card['sees']
    if sees['profile'] == 'spec-denied':
        return None if rel in PLAN_AND_CONTRACT else 'outside_profile'
    if rel in ALWAYS:
        return ALWAYS[rel]
    screened = _screen_class(card, cls) if cls else None
    if screened is not None:
        return screened
    if sees['profile'] == 'blind' and not _reachable(card, rel):
        return 'outside_profile'
    return None


def _packet(binding):
    """The manifest and ``{source_path: bytes}`` of a written packet, read from its folder."""
    root = Path(binding['path'])
    manifest = json.loads((root / 'manifest.json').read_text())
    carried = {a['source_path']: (root / a['path']).read_bytes() for a in manifest['artifacts']}
    return manifest, carried


@dimension_case('ROLE', 'sees', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('sees',)), ids=str)
def test_role_sees_screens_every_forbidden_input_class(nc, row):
    from ravel.workflow import review_projection as rp
    card, field, _ = role_row(row)
    assert field == 'sees'
    profile = card['sees']['profile']
    declared = sorted(card['sees'].get('forbidden_inputs', []))
    missing = [c for c in declared if c not in PLANTS]
    assert not missing, f'{card["id"]} declares input classes this case plants nothing for: {missing}'
    run = nc.root / 'run'
    run.mkdir()
    plan = _plant(nc, run, card)
    packets = nc.root / 'packets'
    packets.mkdir()
    holders = [packets, nc.state]
    canaries = [c for _, _, c in plan['files'].values()]

    unknown = [c for c in declared if c not in rp.CLASSES]
    if unknown:
        # Fail closed: this installation's screening does not know a class the card declares, so it
        # produces no packet and classifies no file rather than carrying anything unscreened.
        for call in (lambda: rp.project(run, deepcopy(card), key='nc-sees', out_root=packets),
                     lambda: rp.raw_input_class(run, deepcopy(card), 'inputs/permitted.txt')):
            with pytest.raises(rp.ProjectionRefused) as refused:
                call()
            assert refused.value.code == 'forbidden_class_unknown', refused.value.code
            assert all(name in str(refused.value) for name in unknown), str(refused.value)
        assert list(packets.iterdir()) == []
        assert [h for c in canaries for h in c.found_in(*holders)] == []
        return

    # The raw-input screen (the check on a worker's pinned inputs) names the class of every planted file.
    for rel, (cls, _, _) in plan['files'].items():
        assert rp.raw_input_class(run, deepcopy(card), rel) == _raw_expectation(card, rel, cls), (card['id'], rel)
    for rel in ALWAYS:
        assert rp.raw_input_class(run, deepcopy(card), rel) == _raw_expectation(card, rel, None), (card['id'], rel)
    for rel in plan['permitted']:  # positive control: a permitted file is carried when the profile reaches it
        assert rp.raw_input_class(run, deepcopy(card), rel) == _raw_expectation(card, rel, None), (card['id'], rel)

    if profile == 'workspace':
        # A producer works in its own workspace; it has no review packet, and the projection says so.
        with pytest.raises(rp.ProjectionRefused) as refused:
            rp.project(run, deepcopy(card), key='nc-sees', out_root=packets)
        assert refused.value.code == 'producer_profile'
        assert list(packets.iterdir()) == []
        return

    binding = rp.project(run, deepcopy(card), key='nc-sees', out_root=packets)
    manifest, carried = _packet(binding)
    omitted = {o['source_path']: o['class'] for o in manifest['omissions']}
    assert manifest['role'] == card['id'] and manifest['profile'] == profile

    # No forbidden-class canary is in any byte of the packet or anything else the case wrote (the manifest is
    # part of the packet), and the packet's own omission list names the class of each reachable planted file.
    for rel, (cls, raw, canary) in plan['files'].items():
        screened = _screen_class(card, cls)
        if screened is None:
            continue
        assert canary.found_in(*holders) == [], (card['id'], rel)
        assert rel not in carried, (card['id'], rel)
        if _reachable(card, rel):
            assert omitted.get(rel) == screened, (card['id'], rel, omitted.get(rel))
    for cls in FIELDS:
        if cls in declared:
            assert nc.effects.canaries[f'field-{cls}'].found_in(*holders) == [], (card['id'], cls)

    # Positive controls: what the card permits and its profile reaches is carried, with only the declared
    # fields withheld from it; what the profile does not reach, and state that is never projected, is not.
    carried_any = False
    for rel, raw in plan['permitted'].items():
        if _reachable(card, rel):
            assert carried.get(rel) == raw, (card['id'], rel)
            carried_any = True
    for rel, (cls, raw, canary) in plan['files'].items():
        if _screen_class(card, cls) is None and _reachable(card, rel):
            assert carried.get(rel) == raw, (card['id'], rel)  # a class the card does not forbid is carried
            carried_any = True
    for rel in plan['fields']:
        if not _reachable(card, rel):
            assert rel not in carried
            continue
        kept = json.loads(carried[rel])
        assert kept['kept'] == KEPT, (card['id'], rel)
        for cls, keys in FIELDS.items():
            for key in keys:
                assert (key in kept) == (cls not in declared), (card['id'], rel, key)
        carried_any = True
    if _reachable(card, PLAN_AND_CONTRACT[1]):
        assert json.loads(carried[PLAN_AND_CONTRACT[1]])['kept'] == KEPT
        carried_any = True
    assert carried_any, f'{card["id"]}: the profile reaches none of the permitted artefacts, so the control is empty'
    # Graph and review state is never projected. Live worker calls are denied to a blind card; a card that
    # is not blind (the record auditor) is shown the published receipts its read paths reach.
    blind = profile in ('blind', 'spec-denied') or (card.get('requires') or {}).get('blind') is True
    for rel, why in ALWAYS.items():
        if why == 'graph_or_review_state' or blind or not _reachable(card, rel):
            assert rel not in carried, (card['id'], rel)
        else:
            assert carried.get(rel) is not None, (card['id'], rel)
    for rel in (r for r in plan['files'] if not _reachable(card, r)):
        assert rel not in carried


register(Mutation('M08', 'ravel.workflow.review_projection:_classify', returns(None),
                  ('test_role_sees_screens_every_forbidden_input_class[ROLE-physics-critic-sees]',
                   'test_role_sees_screens_every_forbidden_input_class[ROLE-integrity-auditor-sees]',
                   'test_role_sees_screens_every_forbidden_input_class[ROLE-consult-higgs-sees]'),
                  why='the screening classifies nothing as forbidden, so every class reaches the packet'))
register(Mutation('M08', 'ravel.workflow.review_projection:_withhold', lambda original: lambda rel, raw, redact: (raw, []),
                  ('test_role_sees_screens_every_forbidden_input_class[ROLE-plan-critic-sees]',
                   'test_role_sees_screens_every_forbidden_input_class[ROLE-physics-critic-sees]'),
                  why='the redaction of withheld fields keeps every field of an otherwise permitted file'))


# --------------------------------------------------------------------------------------------- tools

DATA = '{"fictional": 1}'
EXEC_NAMES = ('exec', 'shell', 'run', 'bash')
NOT_OFFERED = {'not_allowlisted'}
READ_DENIED = {'forbidden_source', 'not_allowlisted'}


def _check_id(check):
    """The id a card's validator or must_check entry has as a registered check (written here, not imported)."""
    if ':' not in check and check.startswith('ravel.'):
        return 'check:' + check.removeprefix('ravel.')
    return check


def _reply_text(reply):
    return json.dumps(reply, sort_keys=True, default=str)


@dimension_case('ROLE', 'tools', binding=INSTALLED)
@pytest.mark.parametrize('row', dimension_rows('ROLE', ('tools',)), ids=str)
def test_role_tools_deny_reads_outside_and_calls_not_declared(nc, row):
    card, field, _ = role_row(row)
    assert field == 'tools'
    tools_card = card['tools']
    worker = InProcessWorker(nc, card, max_calls=80)
    workspace, run = worker.workspace, worker.run
    offered = {t['name']: t['executes_through']['action'] for t in worker.tools if t['executes_through']['action']}
    reads = 'ws_read' in offered
    secret = nc.effects.canary('secret').value
    other = nc.effects.canary('run-file').value
    outside = Sentinels(run / 'secret', {'data.txt': secret, 'nested/more.txt': secret})
    marker = Sentinels(run / 'marker', {'keep.txt': 'untouched'})
    (run / 'outputs').mkdir(exist_ok=True)
    (run / 'outputs' / 'producer.json').write_text(json.dumps({'note': other}))  # a run file outside read_paths
    (workspace / 'inputs' / 'data.json').write_text(DATA)
    (workspace / 'calls' / 'receipt.json').write_text('{"fictional": 2}')
    os.symlink(run / 'secret' / 'data.txt', workspace / 'inputs' / 'link-out.txt')
    os.symlink(run / 'secret', workspace / 'inputs' / 'dir-out')
    escape = os.path.relpath(run / 'secret' / 'data.txt', workspace)
    assert escape.startswith('..')

    # Reads: each of these paths leaves the card's read paths (the workspace roots the card's inputs are copied
    # into), by escape, absolute path, link or because the file is outside them.
    read_attacks = [escape, 'inputs/' + escape, str(run / 'secret' / 'data.txt'), 'secret/data.txt', 'inputs/dir-out/data.txt',
                    'inputs/link-out.txt', 'inputs/../../../secret/data.txt', 'calls/receipt.json', 'outputs/producer.json',
                    '/etc/hosts', '']
    # Validators the card does not declare, and exec argvs beyond (or without) a declared prefix.
    declared_checks = {_check_id(c) for c in [*card['must_check'], *tools_card['validators']]}
    undeclared = [c for c in ('check:fictional.undeclared', 'check:higgs.measurement_bundle',
                              'check:validation.input_closure.check') if c not in declared_checks]
    assert undeclared
    assert tools_card['read_paths'] and all(not Path(p).is_absolute() and '..' not in Path(p).parts
                                            for p in tools_card['read_paths'])
    prefixes = [list(p) for p in tools_card['exec_argv_prefixes']]
    beyond = ['python3', '-I', '-c', f'open({str(marker.root / "written.txt")!r}, "w").write("x")']
    argvs = [beyond, ['fictional-binary', '--flag']] + [p + ['fictional-argument'] for p in prefixes]

    actions = [{'op': 'list'}]
    actions.append({'op': 'call', 'name': 'ws_read', 'arguments': {'path': 'inputs/data.json'}})  # positive control
    actions += [{'op': 'call', 'name': 'ws_read', 'arguments': {'path': path}} for path in read_attacks]
    actions += [{'op': 'call', 'name': 'check_' + c.split(':', 1)[1].replace('.', '_'), 'arguments': {'paths': []}}
                for c in undeclared]
    actions += [{'op': 'call', 'name': 'check run', 'arguments': {'check_id': c}} for c in undeclared]
    actions += [{'op': 'call', 'name': name, 'arguments': {'argv': argv}} for name in EXEC_NAMES for argv in argvs[:1]]
    actions += [{'op': 'call', 'name': 'exec', 'arguments': {'argv': argv}} for argv in argvs[1:]]
    # Raw broker action names are not tool names: each is refused as an unlisted tool.
    actions += [{'op': 'call', 'name': name, 'arguments': args} for name, args in
                (('read', {'path': 'inputs/data.json'}), ('write', {'path': 'outputs/x.txt', 'content': 'x'}))]
    knowledge = 'knowledge_find' in offered
    if knowledge:
        # A listed tool with arguments outside its schema is refused at the toolbelt guard.
        actions.append({'op': 'call', 'name': 'knowledge_find', 'arguments': {'text': 'fictional query', 'limit': 51}})
        actions.append({'op': 'call', 'name': 'knowledge_find', 'arguments': {'text': 'fictional query', 'limit': 0}})
    log = worker.play({'actions': actions})
    rows = worker.ledger()
    calls = actions[1:]
    assert len(rows) == len(calls) and all(entry['ok'] for entry in log), [(r['action'], r['status']) for r in rows]
    listing = log[0]
    assert listing['ok'] and sorted(listing['result']['names']) == sorted(offered)

    # No tool executes a program, whatever prefixes the card declares; a tool that runs a check runs only a
    # check the card declares.
    assert not (set(offered) & set(EXEC_NAMES)) and 'exec' not in offered.values()
    for tool in worker.tools:
        if tool['executes_through']['action'] == 'check run':
            assert _check_id(tool['executes_through']['fixed_args']['check_id']) in declared_checks, tool['name']

    control, read_rows = rows[0], rows[1:1 + len(read_attacks)]
    if reads:
        assert (control['action'], control['status'], control['reply']['error']) == ('read', 'ok', None)
        assert control['reply']['stdout_tail'] == DATA  # a read inside the granted roots is served
        for path, found in zip(read_attacks, read_rows):
            error = found['reply']['error'] or {}
            assert found['action'] == 'read' and found['status'] == 'refused', (card['id'], path, found)
            assert error.get('code') in READ_DENIED and found['reply']['outputs'] == [], (card['id'], path, error)
    else:
        # A card that requires no tools is offered none: even the read inside the workspace is refused.
        assert offered == {} and card['requires']['tools'] == 'none'
        for path, found in zip(['inputs/data.json', *read_attacks], rows[:1 + len(read_attacks)]):
            error = found['reply']['error'] or {}
            assert (found['action'], found['status'], error.get('code')) == ('tool:ws_read', 'refused', 'not_allowlisted'), path
    cursor = 1 + len(read_attacks)
    for found in rows[cursor:cursor + 2 * len(undeclared)]:
        error = found['reply']['error'] or {}
        assert found['status'] == 'refused' and error.get('code') in NOT_OFFERED, (card['id'], found['action'], error)
        assert found['action'] in {'tool:check run'} or found['action'].startswith('tool:check_'), found['action']
    cursor += 2 * len(undeclared)
    for found in rows[cursor:cursor + len(EXEC_NAMES) + len(argvs) - 1 + 2]:
        error = found['reply']['error'] or {}
        assert found['status'] == 'refused' and error.get('code') == 'not_allowlisted', (card['id'], found['action'], error)
        assert found['action'].startswith('tool:') and found['reply']['outputs'] == [], found
    cursor += len(EXEC_NAMES) + len(argvs) - 1 + 2
    if knowledge:
        refused, served = rows[cursor], rows[cursor + 1]
        error = refused['reply']['error'] or {}
        assert (refused['action'], refused['status'], error.get('code')) == ('knowledge query', 'refused', 'not_allowlisted'), refused
        assert (served['action'], served['status'], served['reply']['error']) == ('knowledge query', 'ok', None), served
        cursor += 2
    assert cursor == len(rows)

    # The same refusals when the broker itself is called with actions no tool of the card executes.
    raw = [{'action': 'exec', 'args': {'argv': beyond}}, {'action': 'exec', 'args': {'argv': argvs[1]}},
           {'action': 'review-context read', 'args': {'path': 'inputs/data.json'}}]
    raw += [{'action': 'check run', 'args': {'check_id': c}} for c in undeclared]
    if 'write' not in offered.values():
        raw.append({'action': 'write', 'args': {'path': 'outputs/raw.txt', 'content': 'x'}})
    for number, request in enumerate(raw):
        reply = worker.broker.call({'call_id': f'raw-{number}', **request})
        assert reply['status'] == 'refused' and (reply['error'] or {}).get('code') == 'not_allowlisted', (request, reply)
        assert reply['outputs'] == []

    # Effects, counted from outside: protected files untouched, nothing run, nothing written, no leaked bytes.
    assert outside.changes() == [] and marker.changes() == []
    assert not (marker.root / 'written.txt').exists()
    assert list((workspace / 'outputs').iterdir()) == []
    assert (run / 'outputs' / 'producer.json').read_text() == json.dumps({'note': other})
    text = _reply_text(worker.ledger()) + _reply_text(log)
    assert secret not in text and other not in text
    assert nc.effects.canaries['secret'].found_in(workspace / 'outputs', workspace / 'scratch', nc.state) == []


def _call_ids_unprefixed(original):
    """An unlisted tool name goes to the broker as the bare action name it spells (no alias guard)."""
    def to_request(tools, name, args, call_id):
        by = {t['name']: t for t in tools}
        if type(name) is str and name not in by:
            return {'call_id': call_id, 'action': name, 'args': args}
        return original(tools, name, args, call_id)
    return to_request


def _confinement_off(original):
    """The broker's workspace policy checks only that the path has components: no escape, no granted roots."""
    def canonical(self, rel, *, write=False):
        return [part for part in rel.split('/') if part not in ('', '.')]
    return canonical


register(Mutation('M07', 'ravel.workflow.tool_gate:broker_guard', lambda original: lambda tools, **kw: (lambda a, b, c: None),
                  ('test_role_tools_deny_reads_outside_and_calls_not_declared[ROLE-analysis-author-tools]',),
                  why='the broker guard admits every call the allowlist lets through'),
         Mutation('M07', 'ravel.workflow.toolbelt:to_request', _call_ids_unprefixed,
                  ('test_role_tools_deny_reads_outside_and_calls_not_declared[ROLE-analysis-author-tools]',),
                  why='an unlisted tool name aliases the broker action it spells'),
         Mutation('M08', 'ravel.workflow.broker:Broker._canonical', _confinement_off,
                  ('test_role_tools_deny_reads_outside_and_calls_not_declared[ROLE-analysis-author-tools]',
                   'test_role_tools_deny_reads_outside_and_calls_not_declared[ROLE-model-builder-tools]'),
                  why='the broker reads any path below the workspace descriptor, including its parents'))
