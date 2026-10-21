"""Node manifests, worker packets, the dispatch check and the instruction-delivery receipt.

``manifest(step, card)`` lists, from the installed catalogue only, every unit a node owes
its worker: the common preamble, the effective card's field units and its must-read
knowledge, the step's declared instruction sources, the judgment protocols its kind or
triggers name, the check-in template of an authority node and the governing skill of
its stage. ``packet`` renders those exact texts with ids and manifest indices beside the full
effective card, the step specification, the inputs by digest and the closed output
schema. Duty units, card units and must-read knowledge are always inline; other context
units move to on-demand retrieval by id only when the packet would exceed its inline
budget, which the step's engagement packet scope may only lower (``inline_context_tokens``:
a lean seat keeps no context unit inline). The packet budget is the seat's declared model
input window (``budget.seat_budget``), never a fixed number. When the mandatory part would not
fit it, the largest step-specification values move by reference: a pinned packet reference
file with its digest, size and a leading excerpt, retained in the controller's packet record.
Only when the mandatory core alone (rules, card, duty units, output contract, the step
skeleton and the capability index) exceeds the budget is the packet refused, with its remedy;
it is never truncated.

``check_packet`` is the dispatch check: it rebuilds the packet from the installed
catalogue and refuses any difference, so an altered, dropped or added unit, card field,
input or schema never reaches a worker.
"""
from __future__ import annotations

import hashlib
import json
import re

from . import catalogue as _catalogue, compiler

PACKET_FORMAT = 'ravel-instruction-packet-v1'
INLINE_ALWAYS = ('card', 'must_read')  # with every duty unit, never deferred
# A step names its check-in as the step schema does (``step.v1`` ``checkin``); the catalogue keys the check-in
# templates CI1, CI2, CI3 and deviation. A template's own name is accepted as it is; any other name is refused.
CHECKIN_TEMPLATES = {'checkin1': 'CI1', 'checkin2': 'CI2', 'checkin3': 'CI3', 'deviation': 'deviation'}


class PacketRefused(ValueError):
    """The packet cannot be built or dispatched; ``reasons`` lists every cause."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__('; '.join(self.reasons))


class PacketBudgetExceeded(PacketRefused):
    """The mandatory core alone exceeds the seat's packet budget; ``remedy`` names the fix."""

    code = 'packet_budget_exceeded'

    def __init__(self, reasons, remedy):
        super().__init__(reasons)
        self.remedy = remedy


# Step-specification values that stay inline whatever the budget: the step's identity and contract.
SPEC_INLINE = ('id', 'kind', 'role', 'stage', 'checkin', 'depends_on', 'outputs', 'inputs', 'instruction_sources',
               'review_source_seats', 'review_census_groups', 'protocols', 'skills', 'description', 'question',
               'route')
REFERENCE_PREFIX = 'packet-reference-'
EXCERPT_CHARS = 600


def _cat():
    return _catalogue.installed()


def _card_problems(cat, card):
    """Differences between an effective card and the catalogue's units for that role."""
    path = compiler.CARD_PATH.format(role=card.get('id'))
    expected = {u['id']: u for u in cat.by_source.get(path, [])}
    if not expected:
        return [f'role {card.get("id")!r} has no card in the installed instruction catalogue']
    actual = {u['id']: u for u in compiler.card_units(card)}
    problems = [f'card unit missing: {uid}' for uid in expected if uid not in actual]
    problems += [f'card unit not in the installed catalogue: {uid}' for uid in actual if uid not in expected]
    problems += [f'card unit differs from the installed catalogue: {uid}' for uid in actual
                 if uid in expected and compiler.digest_text(actual[uid]['text']) != expected[uid]['sha256']]
    return problems


def _skill_selectors(cat, step):
    """The governing skills a step owes: by its stage, by a workflow source that a skill governs, or
    named explicitly in ``skills`` (a scan route names its scan skill at the statistics stage)."""
    sources = {s.split('#')[0] for s in step.get('instruction_sources') or []}
    selected = [rule['skill'] for rule in cat.manifests['governing_skills']
                if step.get('stage') in rule.get('stages', []) or sources & set(rule.get('sources', []))]
    return [f'skill:{name}' for name in dict.fromkeys(selected + list(step.get('skills') or [])) if name]


def manifest(step: dict, card: dict | None) -> dict:
    """The instruction manifest of one node: units with id, sha256, kind and why they are included."""
    cat = _cat()
    man = cat.manifests
    if step.get('role') and card is None:
        raise PacketRefused(['a role seat requires its full effective card'])
    if card is not None:
        problems = _card_problems(cat, card)
        if step.get('role') not in (None, card.get('id')):
            problems.append(f'step {step.get("id")!r} names role {step["role"]!r}, not the card {card.get("id")!r}')
        if problems:
            raise PacketRefused(problems)
    groups = [('preamble', list(man['preamble']))]
    if card is not None:
        groups.append(('card', [f'card:{card["id"]}']))
        groups.append(('must_read', [f'knowledge:{i}' for i in card['knowledge']['must_read']]))
    if step.get('operation') in man.get('operations', {}):
        groups.append(('operation', ['operation:' + step['operation']]))
    groups.append(('source', list(step.get('instruction_sources') or [])))
    protocols = list(dict.fromkeys([*man['step_kinds'].get(step.get('kind'), []), *(step.get('protocols') or [])]))
    groups.append(('protocol', [f'protocol:{p}' for p in protocols]))
    if step.get('checkin'):
        groups.append(('checkin', [f'checkin:{CHECKIN_TEMPLATES.get(step["checkin"], step["checkin"])}']))
    groups.append(('skill', _skill_selectors(cat, step)))
    entries, seen, missing = [], set(), []
    for via, selectors in groups:
        for selector in selectors:
            try:
                ids = cat.resolve(selector)
            except KeyError as exc:
                missing.append(str(exc.args[0]))
                continue
            for uid in ids:
                if uid in seen:
                    continue
                seen.add(uid)
                unit = cat.units[uid]
                entry = {'id': uid, 'sha256': unit['sha256'], 'kind': unit['kind'], 'via': via}
                if unit.get('review_required'):
                    entry['review_required'] = True
                entries.append(entry)
    # Folded roles retain their complete installed manifests. Shared units keep
    # their first index; new units follow the seat's own units in source order.
    for folded in (step.get('engagement') or {}).get('folded_manifests') or ():
        if not isinstance(folded, dict) or not isinstance(folded.get('units'), list):
            missing.append('folded manifest is malformed')
            continue
        problems = manifest_problems(folded)
        if problems:
            missing.extend('folded ' + problem for problem in problems)
            continue
        for row in folded['units']:
            uid = row['id']
            if uid in seen:
                continue
            seen.add(uid)
            unit = cat.units[uid]
            entry = {'id': uid, 'sha256': unit['sha256'], 'kind': unit['kind'], 'via': 'folded'}
            if unit.get('review_required'):
                entry['review_required'] = True
            entries.append(entry)
    if missing:
        raise PacketRefused(missing)
    body = {'schema_version': 1, 'kind': 'instruction-manifest', 'step': step.get('id'),
            'role': card['id'] if card is not None else None, 'catalogue_sha256': cat.sha256, 'units': entries}
    return {**body, 'sha256': compiler.digest_value(body)}


_node_manifest = manifest  # check_packet's own parameter is named after the delivered manifest


def manifest_problems(manifest: dict, card: dict | None = None) -> list[str]:
    """A manifest that no longer matches its own digest or the installed catalogue."""
    cat = _cat()
    problems = []
    body = {k: v for k, v in manifest.items() if k != 'sha256'}
    if compiler.digest_value(body) != manifest.get('sha256'):
        problems.append('manifest digest differs from its content')
    if manifest.get('catalogue_sha256') != cat.sha256:
        problems.append('manifest names a different instruction catalogue than the installed one')
    for entry in manifest.get('units', []):
        unit = cat.units.get(entry.get('id'))
        if unit is None:
            problems.append(f'unit not in the installed catalogue: {entry.get("id")}')
        elif unit['sha256'] != entry.get('sha256') or unit['kind'] != entry.get('kind'):
            problems.append(f'unit differs from the installed catalogue: {entry["id"]}')
    if card is not None:
        if manifest.get('role') != card.get('id'):
            problems.append(f'manifest is for role {manifest.get("role")!r}, not {card.get("id")!r}')
        problems += _card_problems(cat, card)
    return problems


def estimate_tokens(text: str, per: int = 4) -> int:
    """A deterministic token estimate: characters over the configured characters per token."""
    return -(-len(text) // per)


def _canonical(value) -> str:
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False)


def seat_scope(step: dict, card: dict | None) -> dict:
    """Project the seat's own role and route contract into its session introduction."""
    from .ack import OUTPUT_SCHEMAS
    declared = card['output']['schema'] if card is not None else 'producer.v1'
    return {'role': card['id'] if card is not None else None,
            'purpose': card['purpose'] if card is not None else step.get('description'),
            'family': card['family'] if card is not None else None,
            'route': step.get('route'), 'kind': step.get('kind'), 'stage': step.get('stage'),
            'operation': step.get('operation'),
            'instruction_sources': list(step.get('instruction_sources') or []),
            'response_schema': OUTPUT_SCHEMAS[declared.rpartition('.v')[0]],
            'output_scope': 'The step specification supplies the declared output artifacts and their schemas.'}


def _unit_block(unit, index: int) -> str:
    return f'--- [{unit["kind"]}] {unit["id"]} index:{index}\n{unit["text"]}\n'


def _packet_spec(step, manifest, inline):
    """Render redundant catalogue text by reference, leaving the step contract intact.

    Only byte-identical text already delivered inline may be replaced. Review
    identities, checks and source bindings remain explicit. Original folded
    manifest digests bind the units listed separately in the complete union.
    """
    from copy import deepcopy
    result = deepcopy(step)
    cat = _cat()
    indices = {row['id']: i for i, row in enumerate(manifest['units'])}
    texts = {}
    source_seats = []
    census_groups = []

    def item_ref(item, pointer):
        if not isinstance(item, dict):
            return
        defaults = {'review_required': 'producer checklist', 'must_check': 'reviewer card'}
        if item.get('kind') in defaults and item.get('source') == defaults[item['kind']]:
            item.pop('source')
        census = item.get('census')
        if isinstance(census, list) and len(_canonical(census)) > 24:
            if census not in census_groups:
                census_groups.append(census)
            item.pop('census')
            item['census_ref'] = census_groups.index(census)
        source_seat, source_item = item.get('source_seat'), item.get('source_item_id')
        if (isinstance(source_seat, str) and isinstance(source_item, str)
                and item.get('id') == source_seat + '/' + source_item):
            # Recoverable exactly from the retained identity and source seat.
            item.pop('source_item_id')
            if source_seat not in source_seats:
                source_seats.append(source_seat)
            item.pop('source_seat')
            item['source_seat_ref'] = source_seats.index(source_seat)
        uid = item.get('unit')
        if uid in indices and 'text' in item:
            unit = cat.units[uid]
            if item['text'] == unit['text'] and item.get('sha256') == unit['sha256']:
                # unit and sha256 already carry the binding; add only its index.
                reference = {'unit_index': indices[uid]}
                if uid in inline:
                    item.pop('text')
                    item.update(reference)
                elif uid in texts:
                    item.pop('text')
                    item.update(reference)
                    item['text_ref'] = texts[uid]
                else:
                    # Deferred context needed by a review is still printed once;
                    # repeated source-seat items point to that exact text.
                    texts[uid] = pointer + '/text'

    engagement = result.get('engagement') or {}
    for i, item in enumerate(engagement.get('items') or ()):
        item_ref(item, f'#/engagement/items/{i}')
    parameters = result.get('parameters') or {}
    engagement_items = {item.get('id'): (i, item) for i, item in
                        enumerate((step.get('engagement') or {}).get('items') or ()) if isinstance(item, dict)}
    for key in ('review_items', 'reviewer_items'):
        for i, item in enumerate(parameters.get(key) or ()):
            if not isinstance(item, dict):
                continue
            shared = engagement_items.get(item.get('id'))
            if shared and shared[1] == item:
                parameters[key][i] = {'id': item['id'], 'engagement_item_index': shared[0]}
            else:
                item_ref(item, f'#/parameters/{key}/{i}')
    if source_seats:
        result['review_source_seats'] = source_seats
    if census_groups:
        result['review_census_groups'] = census_groups
    if 'folded_manifests' in engagement:
        engagement['folded_manifests'] = [
            {k: v for k, v in folded.items() if k != 'units'}
            for folded in engagement['folded_manifests']]
    if 'folded_cards' in engagement:
        rendered = []
        for folded in engagement['folded_cards']:
            ids = cat.resolve(f'card:{folded["id"]}')
            if not _card_problems(cat, folded) and all(uid in indices for uid in ids):
                rendered.append({'id': folded['id'], 'sha256': compiler.digest_value(folded)})
            else:
                rendered.append(folded)
        engagement['folded_cards'] = rendered
    return result


def packet(manifest: dict, card: dict | None, step: dict, inputs: list[dict], *, budget: dict | None = None) -> dict:
    """The worker packet: exact unit texts, the whole effective card, the step, inputs and output schema.

    ``budget`` is the seat's packet budget (``budget.seat_budget``); without one the catalogue projection
    for the card's tiers applies."""
    problems = manifest_problems(manifest, card)
    if manifest.get('step') != step.get('id'):
        problems.append(f'manifest is for step {manifest.get("step")!r}, not {step.get("id")!r}')
    if problems:
        raise PacketRefused(problems)
    from .ack import output_schema
    schema_id, schema = output_schema(card, manifest)
    cat = _cat()
    settings = cat.manifests.get('packet', {})
    from . import budget as _budget
    try:
        budget = _budget.seat_budget(card) if budget is None else budget
    except _budget.BudgetUnavailable as exc:
        raise PacketBudgetExceeded([str(exc)], exc.remedy) from exc
    limit = budget['packet_tokens']
    if type(limit) is not int or limit <= 0:
        raise PacketRefused([f'invalid packet budget {limit!r}'])
    # The engagement packet scope (``step.engagement``) can only lower the inline budget: a lean seat defers its
    # context units; duty units, the card and its must-read knowledge stay inline at every scope.
    bound = settings.get('inline_tokens', 120000)
    scoped = (step.get('engagement') or {}).get('inline_context_tokens')
    if scoped is not None:
        if type(scoped) is not int or scoped < 0:
            raise PacketRefused([f'invalid engagement context-token bound {scoped!r}'])
        bound = min(bound, scoped)
    units = [cat.units[e['id']] for e in manifest['units']]
    indices = {entry['id']: index for index, entry in enumerate(manifest['units'])}
    always = {e['id'] for e in manifest['units'] if e['kind'] == 'duty' or e['via'] in INLINE_ALWAYS}
    duty = [u for u in units if u['id'] in always]
    context = [u for u in units if u['id'] not in always]
    scope = ['== Seat scope ==', _canonical(seat_scope(step, card)), '']
    head = [f'{PACKET_FORMAT}',
            f'step: {step.get("id")}   role: {card["id"] if card else "-"}   manifest sha256: {manifest["sha256"]}',
            f'instruction catalogue sha256: {cat.sha256}',
            f'units: {len(units)} ({len(duty)} duty, {len(context)} context)', '']
    rules = ['== Acknowledgement ==',
             'Every duty unit below needs exactly one row in the final record\'s checklist[]: '
             '{"unit": <unit id>, "status": "done" | "not_applicable" | "blocked", '
             '"evidence": "<output path>#<pointer>" or "final_record#<json pointer>", "note": <text or null>}.',
             'Alternatively checklist may be {"schema_version": 1, "groups": '
             '[{"indices": [<manifest unit index>, ...], "status": <status>, "evidence": <pointer or null>, '
             '"note": <text or null>}]}. Indices are zero-based positions in the complete pinned manifest units '
             'array, printed on each unit below. Each group applies its status, evidence and note separately '
             'to every listed unit. List every duty index exactly once; omitted, duplicate, out-of-range or '
             'conflicting indices are refused. There is no default status.',
             'done needs evidence in an output written in this attempt, or in a final record field outside '
             'checklist and instruction_ack; not_applicable and blocked need a note; '
             'blocked holds the step with that note. Set instruction_ack.manifest_sha256 to this packet\'s manifest sha256. '
             'Context units need no row. Obedience to these instructions is your responsibility and is reviewed; '
             'this packet and its receipt prove only that you received them.', '']
    rules += ['Reviewer items with unit_index reference the inline unit by their unit id, sha256 and manifest index. '
              'Folded manifest sha256 binds the complete original manifest; its units are listed in this packet. '
              'text_ref points to identical review text printed once in the step specification '
              '(a JSON pointer from its root). source_seat_ref indexes review_source_seats; source_item_id is the '
              'suffix of id after that source seat + "/". A parameter item with engagement_item_index refers to '
              'the complete item at that index in engagement.items. census_ref indexes review_census_groups. '
              'When source is omitted, review_required means "producer checklist" and must_check means '
              '"reviewer card". Folded cards are identified by digest; '
              'their fields are catalogue units in this packet; '
              'their duty units are inline and their context follows this packet scope.', '']
    from ravel.workflow import capability_catalogue
    seat_kind = str((step.get('parameters') or {}).get('seat_kind') or step.get('role') or step.get('kind') or 'worker')
    try:
        capabilities = capability_catalogue.for_seat(seat_kind)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PacketRefused(['capability catalogue unavailable: ' + str(exc)]) from exc
    # A compact index: every entry's id and cost class. The complete rows travel as the pinned shards.
    capability_text = ['== Capability catalogue (index; complete data supplied with this packet) ==',
        'Complete applicability, prerequisites, outputs, summaries, cost classes and source provenance are in '
        'the capabilities-*.json input shards (inside inputs/packet/artifacts/ for a projected role); read the '
        'rows of every entry you consider before choosing the next workflow. '
        'Fragment paths locate exact values in the complete capability context; combine all shards. '
        'Prerequisite references resolve through catalogue.prerequisite_sets; source paths through catalogue.sources. '
        'The full inventory indexed below is independent of cost, engagement tier and current installation.',
        'catalogue sha256: ' + capabilities['catalogue_sha256'],
        *capability_catalogue.POLICY.values(),
        *[row['id'] + ' | cost=' + str(row['cost_class']) for row in capabilities['catalogue']['entries']], '']
    per = settings.get('chars_per_token', 4)
    rendered_spec = _packet_spec(step, manifest, always)
    card_text = ['== Effective role card (every field) ==', _canonical(card) if card is not None else '(no role card)', '']
    listed = ['== Inputs (by digest) =='] + ([f'- {_canonical(row)}' for row in inputs] or ['- (none)']) + ['']
    output = ['== Output contract ==', f'schema: {schema_id}',
              json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(',', ':')), '']
    duty_text = ['== Duty units (acknowledge each), the card and its must-read knowledge =='] + \
        [_unit_block(u, indices[u['id']]) for u in duty]

    def compose(spec_value, references):
        spec = ['== Step specification (step.v1) ==',
                json.dumps(spec_value, sort_keys=True, ensure_ascii=False, separators=(',', ':')), '']
        note = []
        if references:
            note = ['== Step values by reference ==',
                    'Each {"$packet_reference": name, ...} value in the step specification is the complete JSON value '
                    'in inputs/<name> (its sha256 and size are given; the excerpt is its leading text). Read every '
                    'referenced value your duties need before acting; the controller retains each one.'] + \
                [f'- {r["name"]} {r["pointer"]} sha256:{r["sha256"]} bytes:{r["bytes"]}' for r in references] + ['']
        return '\n'.join([PACKET_FORMAT, *scope, *rules, *head[1:], *spec, *note, *card_text, *listed, *output,
                          *capability_text, *duty_text])

    references = []
    fixed = compose(rendered_spec, references)
    if estimate_tokens(fixed, per) > limit:
        rendered_spec, references = _by_reference(rendered_spec, lambda value, refs: estimate_tokens(
            compose(value, refs), per) <= limit)
        fixed = compose(rendered_spec, references)
    if estimate_tokens(fixed, per) > limit:
        raise PacketBudgetExceeded(
            [f'the mandatory packet core exceeds the packet budget for role {manifest.get("role")}: about '
             f'{estimate_tokens(fixed, per)} tokens with every step value by reference, against {limit} '
             f'({budget["basis"]}, binding model {budget["binding_model"]!r}); not truncated'],
            'serve this seat with a model whose declared context window is larger (the model catalogue lists each '
            "model's context_tokens), or narrow the step so its duties and contract are smaller")
    bound = min(bound, limit)
    context_text = ['== Context units =='] + [_unit_block(u, indices[u['id']]) for u in context]
    inline = '\n'.join(context_text)
    if not context or estimate_tokens(fixed, per) + estimate_tokens(inline, per) <= bound:
        deferred = []
        text = fixed + '\n' + inline
    else:
        deferred = [u['id'] for u in context]
        text = fixed + '\n' + '\n'.join(
            ['== Context units on request ==',
             'These context units are served verbatim by the knowledge broker: request one by its id; '
             'each request is logged.'] + [f'- {u["id"]} index:{indices[u["id"]]}' for u in context]) + '\n'
    tokens = estimate_tokens(text, per)
    if tokens > limit:
        raise PacketBudgetExceeded([f'instruction packet exceeds the packet budget for role {manifest.get("role")}: '
                                    f'about {tokens} tokens against {limit}; not truncated'],
                                   'serve this seat with a model whose declared context window is larger')
    return {'text': text, 'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(), 'schema': schema,
            'schema_id': schema_id, 'manifest_sha256': manifest['sha256'], 'catalogue_sha256': cat.sha256,
            'units': [u['id'] for u in units if u['id'] not in deferred], 'deferred': deferred,
            'capability_context': capabilities, 'tokens': tokens, 'budget': budget, 'references': references}


def reference_bytes(reference: dict) -> bytes:
    """The exact file bytes of one packet reference (its pinned JSON value)."""
    return (json.dumps(reference['value'], sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()


def _by_reference(spec, fits):
    """Move the largest step values out of ``spec`` until ``fits(spec, references)`` holds.

    Only values below the step's identity and contract keys move (``SPEC_INLINE`` stays inline);
    each becomes ``{"$packet_reference", "sha256", "bytes", "excerpt"}`` and its complete value is
    returned for the controller to pin and retain. Deterministic: the largest value first, ties by
    pointer. Returns the rendered spec and the references (possibly still too large; the caller refuses).
    """
    from copy import deepcopy
    value = deepcopy(spec)
    references = []

    def candidates(node, pointer, depth):
        if isinstance(node, dict):
            items = node.items()
        elif isinstance(node, list):
            items = enumerate(node)
        else:
            return
        for key, child in items:
            if depth == 0 and key in SPEC_INLINE:
                continue
            if isinstance(child, dict) and '$packet_reference' in child:
                continue
            path = pointer + '/' + str(key).replace('~', '~0').replace('/', '~1')
            size = len(json.dumps(child, sort_keys=True, ensure_ascii=False, separators=(',', ':')))
            if depth > 0 and size > EXCERPT_CHARS + 200:
                yield size, path, node, key
            yield from candidates(child, path, depth + 1)

    while not fits(value, references):
        found = sorted(candidates(value, '#', 0), key=lambda c: (-c[0], c[1]))
        if not found:
            break
        _, pointer, parent, key = found[0]
        child = parent[key]
        reference = {'name': f'{REFERENCE_PREFIX}{len(references):03d}.json', 'pointer': pointer, 'value': child}
        raw = reference_bytes(reference)
        reference.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        text = raw.decode('utf-8')
        parent[key] = {'$packet_reference': reference['name'], 'sha256': reference['sha256'],
                       'bytes': reference['bytes'], 'excerpt': text[:EXCERPT_CHARS]}
        references.append(reference)
    return value, references


def check_packet(packet_: dict, manifest: dict, card: dict | None, step: dict, inputs: list[dict], *,
                 budget: dict | None = None) -> list[str]:
    """The dispatch check: errors when the packet is not exactly the one the installed catalogue yields."""
    try:
        node = _node_manifest(step, card)
        expected = packet(manifest, card, step, inputs, **({'budget': budget} if budget is not None else {}))
    except PacketRefused as exc:
        return exc.reasons
    problems = []
    if manifest.get('sha256') != node['sha256']:
        problems.append('manifest differs from the node manifest the installed catalogue yields for this step')
        delivered = {e['id'] for e in manifest.get('units', [])}
        owed = {e['id'] for e in node['units']}
        problems += [f'unit dropped from the manifest: {uid}' for uid in sorted(owed - delivered)]
        problems += [f'unit added to the manifest: {uid}' for uid in sorted(delivered - owed)]
    text = packet_.get('text')
    if not isinstance(text, str) or hashlib.sha256(text.encode('utf-8')).hexdigest() != packet_.get('sha256'):
        problems.append('packet digest differs from its text')
    if packet_.get('sha256') != expected['sha256']:
        problems.append('packet differs from the installed instruction catalogue')
        if isinstance(text, str):
            cat = _cat()
            indices = {entry['id']: index for index, entry in enumerate(manifest['units'])}
            for uid in expected['units']:
                if _unit_block(cat.units[uid], indices[uid]) not in text:
                    problems.append(f'unit missing or altered in the packet: {uid}')
            if card is not None and _canonical(card) not in text:
                problems.append('effective card missing or altered in the packet')
    if packet_.get('schema') != expected['schema'] or packet_.get('schema_id') != expected['schema_id']:
        problems.append('packet output schema differs from the contract')
    if packet_.get('deferred') != expected['deferred']:
        problems.append('packet defers a different set of context units')
    if packet_ != expected:
        problems.append('packet fields differ from the rebuilt packet')
    return problems


def serve(unit_id: str) -> dict:
    """One unit verbatim for on-demand retrieval (the knowledge broker's instruction action)."""
    unit = _cat().units.get(unit_id)
    if unit is None:
        raise KeyError('unknown instruction unit: ' + unit_id)
    return {'id': unit['id'], 'kind': unit['kind'], 'sha256': unit['sha256'], 'text': unit['text']}


def receipt(manifest: dict, packet_: dict, *, session: str | None) -> dict:
    """Uncredited receipt payload; only record_delivery validates and stores a delivery."""
    return {'schema_version': 1, 'kind': 'instruction-delivery', 'step': manifest.get('step'),
            'role': manifest.get('role'), 'manifest_sha256': manifest['sha256'],
            'catalogue_sha256': manifest['catalogue_sha256'], 'packet_sha256': packet_['sha256'],
            'schema_id': packet_['schema_id'], 'units': [e['id'] for e in manifest['units']],
            'duty_units': sum(1 for e in manifest['units'] if e['kind'] == 'duty'),
            'deferred': list(packet_.get('deferred', [])), 'session': session,
            'capability_catalogue_sha256': packet_['capability_context']['catalogue_sha256']}


def record_delivery(store, manifest: dict, packet_: dict, *, session: str | None) -> str:
    """Append only a rebuilt packet bound to an observed current worker session."""
    from .custody import session_observation
    try:
        observed = session_observation(store, session, manifest)
        if packet_ != observed['packet']:
            raise ValueError('delivery packet differs from the controller-observed session packet')
    except (AttributeError, KeyError, TypeError, OSError, ValueError) as exc:
        raise PacketRefused(['unobserved instruction delivery: ' + str(exc)]) from exc
    body = receipt(manifest, packet_, session=session)
    body.update(run_id=observed['run_id'], attempt=observed['attempt'])
    return store.append('instruction-delivery', body)


def obligations(manifest: dict) -> dict[str, list[str]]:
    """{census id: [unit ids]} for every census obligation the manifest's units state."""
    cat = _cat()
    result = {}
    for entry in manifest['units']:
        for census_id in cat.units[entry['id']].get('census', []):
            result.setdefault(census_id, []).append(entry['id'])
    return result


MECHANISM_ROWS = {'I01': 'installed-source-and-packet', 'I02': 'complete-packet-and-ack',
                  'E29': 'governing-skill-and-ack', 'CF03': 'full-must-read-and-ack',
                  'CF13': 'full-effective-card-and-ack', 'CT02': 'all-units-and-ack'}
_ROLE_DELIVERY = re.compile(r'ROLE-.+-(?:purpose|knowledge|protocol-\d+)$')


def discharge(store, entries: dict[str, str], manifest: dict, *, receipt_id: str, ack_errors: list[str] | None = None,
              record=None) -> dict[str, str]:
    """Credit only store-held current delivery and completion observations.

    ack_errors is retained for existing callers but confers no authority: errors are recomputed
    from the observed final record, pinned schema and output bytes. Mechanism rows have explicit
    bindings below; role purpose/protocol/knowledge rows bind their delivered units. Other card
    fields remain pending for their enforcement owner, even when delivered as duties.
    """
    if record is None:
        from ravel.controller import ledger
        record = ledger.record
    from .ack import check_ack
    from .custody import _read, session_observation, completion_observation, observed_completion
    from jsonschema import Draft202012Validator
    completion = None
    try:
        delivered = _read(store, 'instruction-delivery', receipt_id)
        session = delivered.get('session')
        observed = session_observation(store, session, manifest)
        expected = receipt(manifest, observed['packet'], session=session)
        expected.update(run_id=observed['run_id'], attempt=observed['attempt'])
        if any(delivered.get(k) != v for k, v in expected.items()):
            raise ValueError('delivery receipt differs from the current session and rebuilt packet')
        completion = completion_observation(store, session, manifest)
        final = completion['final_record']
        with observed_completion(store, session=session):
            errors = check_ack(manifest, final, [r['path'] for r in completion['artifacts']])
        errors += ['schema: ' + e.message for e in
                   Draft202012Validator(observed['packet']['schema']).iter_errors(final)]
    except (AttributeError, KeyError, TypeError, OSError, ValueError) as exc:
        errors = ['manifest: instruction custody failed: ' + str(exc)]
    stated = obligations(manifest)
    kinds = {e['id']: e['kind'] for e in manifest['units']}
    general = [e for e in errors if e.startswith(('manifest:', 'schema:'))]
    statuses = {}
    for census_id, entry_id in sorted(entries.items()):
        units = stated.get(census_id, [])
        mechanism = MECHANISM_ROWS.get(census_id)
        if mechanism:
            units = [e['id'] for e in manifest['units']]
            faults = list(errors)
            if census_id in ('CF03', 'CF13') and not manifest.get('role'):
                faults.append('manifest: a role packet is required for this mechanism')
            if census_id == 'E29' and not any(e.get('via') == 'skill' for e in manifest['units']):
                faults.append('manifest: no governing skill was delivered')
        elif _ROLE_DELIVERY.fullmatch(census_id):
            faults = general + [e for e in errors if any(e.split(': ', 2)[1:2] == [u] for u in units)]
        elif units and not general:
            statuses[census_id] = 'pending'  # another mechanism owns this row
            continue
        else:
            faults = general
        holds = [e for e in faults if e.startswith('blocked:')]
        if holds and len(holds) == len(faults):
            statuses[census_id] = 'pending'  # a blocked duty holds the step; the entry stays pending
            continue
        if units and not faults and all(kinds[u] == 'context' for u in units):
            statuses[census_id] = 'pending'  # delivered, never acknowledged: not this node's to discharge
            continue
        if not units:
            status = 'violated'
            evidence = {'instruction_receipt': receipt_id, 'units': [], 'reason': 'no delivered unit states it'}
        elif faults:
            status = 'violated'
            evidence = {'instruction_receipt': receipt_id, 'units': units, 'errors': faults,
                        'reason': '; '.join(faults)}
        else:
            status = 'satisfied'
            evidence = {'instruction_receipt': receipt_id, 'units': units, 'ack': completion['id']}
            evidence['completion_sha256'] = compiler.digest_value(completion)
            evidence['session'] = completion['session']
            if mechanism:
                evidence['mechanism'] = mechanism
        record(store, entry_id, status, evidence)
        statuses[census_id] = status
    return statuses
