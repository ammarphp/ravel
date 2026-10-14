"""Compile declared experiment choices into fresh ordinary scientific inputs.

This is a finite template compiler, not an experiment runner or acceptance
journal. Original scientific policy/source/resource fields are retained. Only
explicit typed input slots and explicit internal path references may change.
The output portfolio still needs its normal Graph input admission, current
phase selection, CHECK-IN 1, execution, role reviews and whole-task synthesis.
"""
from copy import deepcopy
from . import provider_transport
import hashlib
import json
from pathlib import Path

from . import agent_graph, research_cycle as cycle, research_followup as follow, science, state_io
from .scientific_artifact import _pointer

MAX_FILES = 32
MAX_TOTAL_BYTES = 16 * 1024 * 1024
EXPERIMENT_FIELDS = {"question", "premise_ids", "cost", "observable", "context_outputs", "acceptance_scope", "exploratory"}


def _context_value(root, parent):
    _, state = cycle._load(root)
    feedback_pin, feedback, reports = None, None, []
    if parent is not None:
        state, feedback, feedback_pin, reports, _ = follow._feedback_content(root, parent)
    hypotheses = [deepcopy(h) for h in state['hypotheses'] if cycle._fresh(state, h['premise_bindings'])]
    if not hypotheses:
        raise ValueError('existing declared concrete hypotheses required; no automatically invented hypothesis')
    return state, {'kind': 'research_blueprint_context', 'cycle_root': str(cycle._ordinary(root)),
        'parent_experiment': parent, 'question': state['contract']['question'], 'scope': state['contract']['scope'],
        'whole_task': deepcopy(state['context']['requested_quantities']),
        'premise_bindings': {p['id']: p['sha256'] for p in state['premises']},
        'hypotheses': hypotheses, 'feedback_pin': feedback_pin, 'feedback': feedback, 'role_content': reports,
        'speculative_ideation_required': False, 'execution_authorized': False, 'physics_validated': False}


def prepare_context(root, output_dir, *, parent=None):
    """Baseline/screen/refinement context; no mandatory brainstorm or model call.

    Existing explicit hypotheses can come from a cited, speculative or supplied
    source. All currently applicable rivals remain in the design denominator.
    Reviewed-parent criticism is included only when a parent is actually chosen.
    """
    _, context = _context_value(root, parent)
    path = cycle._ordinary(output_dir)
    if path.exists() or not path.is_relative_to(cycle._ordinary(root)) or path == cycle._ordinary(root):
        raise ValueError('fresh blueprint context within its research cycle required')
    return _write(path / 'context.json', _json_bytes(context))


def _context(root, pin, base):
    value = follow._json(pin, base)
    if value.get('kind') == 'research_design_context':
        return follow._current_context(root, pin)
    if value.get('kind') != 'research_blueprint_context' or value.get('cycle_root') != str(cycle._ordinary(root)):
        raise ValueError('current ordinary blueprint or explicit two-stream design context required')
    state, current = _context_value(root, value['parent_experiment'])
    if current != value:
        raise ValueError('blueprint question, full rival census, premise or actual parent feedback changed')
    return state, current


def bound_portfolio(proposal, context, *, proposal_base, context_pin, presented_pins):
    if 'stage_correspondence' in proposal:
        from . import resonance_study
        resonance_study.portfolio_correspondence(proposal, proposal_base, presented_pins)
    if context.get('kind') == 'research_design_context':
        return follow.bound_portfolio(proposal, context, proposal_base=proposal_base,
            context_pin=context_pin, presented_pins=presented_pins)
    state, current = _context(context['cycle_root'], context_pin, proposal_base)
    cycle.ce.keys(proposal, {'kind', 'parent_experiment', 'context_sha256', 'reason', 'experiments'} |
                  ({'stage_correspondence'} if 'stage_correspondence' in proposal else set()))
    cycle._text(proposal['reason'])
    if (current != context or proposal['kind'] != 'research_portfolio'
            or proposal['context_sha256'] != context_pin['sha256'] or proposal['parent_experiment'] != context['parent_experiment']):
        raise ValueError('complete current ordinary blueprint context required for portfolio admission')
    rows = proposal['experiments']
    if type(rows) is not list or not 1 <= len(rows) <= 8 or len({e['id'] for e in rows}) != len(rows):
        raise ValueError('bounded distinct ordinary baseline/screen/discriminating studies required')
    if context_pin['sha256'] not in {p['sha256'] for p in presented_pins}:
        raise ValueError('complete current blueprint context must be a normal Graph input')
    if not {h['id'] for h in context['hypotheses']} <= {h for e in rows for h in e['predictions']}:
        raise ValueError('every current rival needs an outcome prediction or explicit unknown')
    trial = deepcopy(state)
    for row in rows:
        if row['parent'] != context['parent_experiment']:
            raise ValueError('exact chosen baseline or refinement parent required')
        cycle._append_design(trial, row)
        added = trial['experiments'][-1]
        cycle._model_input_admission(added, added['input_pins'], presented_pins, state['base_dir'])
    return deepcopy(proposal)


def adopt_portfolio(root, graph_root, *, node_id, context_pin):
    """Use the existing immutable cycle journal; no separate acceptance state."""
    _, state = cycle._load(root)
    context = follow._json(context_pin, state['base_dir'])
    if context['kind'] == 'research_design_context':
        return follow.adopt_portfolio(root, graph_root, node_id=node_id, context_pin=context_pin)
    with state_io.file_lock(Path(root) / 'operation.lock', blocking=False):
        state, context = _context(root, context_pin, state['base_dir'])
        if str(cycle._ordinary(graph_root)) not in {g['root'] for g in state['graphs']}:
            raise ValueError('actual cumulatively charged designer Graph required')
        origin = cycle._graph_result(graph_root, node_id)
        if origin['role'] != 'designer' or origin['value'].get('kind') not in {'model_result', 'ravel_tool_result'}:
            raise ValueError('actual completed structured designer result required')
        proposal = bound_portfolio(origin['value']['value'], context, proposal_base=state['base_dir'],
            context_pin=context_pin, presented_pins=origin['inputs'])
        trial = deepcopy(state)
        for row in proposal['experiments']:
            cycle._append_design(trial, row)
            added = trial['experiments'][-1]
            added['constructive_origin'] = {**origin, 'design_context': deepcopy(context_pin),
                'complete_current_rivals_presented': True, 'independent_scientific_review': False}
            if row['parent'] is not None:
                trial['revisions'].append({'parent': row['parent'], 'candidate': row['id'],
                    'feedback': context['feedback_pin'], 'origin': added['constructive_origin'],
                    'reason': proposal['reason'], 'incumbent_and_negative_results_retained': True, 'old_votes_carried': []})
        return cycle._commit(Path(root), trial, 'typed_blueprint_portfolio_adopted',
            experiment_ids=[e['id'] for e in proposal['experiments']])


def _identity(stat):
    return (stat.st_dev, stat.st_ino, stat.st_mode, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def _tokens(pointer):
    if type(pointer) is not str or not pointer.startswith('/') or len(pointer) > 1024:
        raise ValueError('bounded explicit non-root pointer required')
    result = []
    for token in pointer[1:].split('/'):
        for index, char in enumerate(token):
            if char == '~' and (index + 1 >= len(token) or token[index + 1] not in '01'):
                raise ValueError('literal JSON pointer escaping required')
        result.append(token.replace('~1', '/').replace('~0', '~'))
    return result


def _replace(document, pointer, value):
    _pointer(document, pointer)  # Existing selectors only, with ASCII list indices.
    tokens = _tokens(pointer)
    parent = document if len(tokens) == 1 else _pointer(document, pointer.rsplit('/', 1)[0])
    if type(parent) is list:
        parent[int(tokens[-1])] = deepcopy(value)
    else:
        parent[tokens[-1]] = deepcopy(value)


def _relative(value):
    if (type(value) is not str or not value or len(value) > 256 or '\\' in value
            or Path(value).is_absolute() or any(x in ('', '.', '..') for x in value.split('/'))):
        raise ValueError('literal confined artifact path required')
    if any(value == name or value.startswith(name + '/') for name in {'study.json', 'portfolio.json', 'materialization.json'}):
        raise ValueError('reserved blueprint output path')
    return value


def _json_bytes(value):
    from .agent_host import _public
    _public(value)
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=True) + '\n').encode('utf-8')


def _validate_slot(value, schema):
    from .agent_host import HostFailure, validate_public_result
    try:
        validate_public_result({'slot': value}, {'type': 'object', 'properties': {'slot': schema},
            'required': ['slot'], 'additionalProperties': False})
    except HostFailure as error:
        raise ValueError('declared typed input slot violated: ' + str(error)) from None


def _decode(raw, form):
    from .agent_host import _loads
    if form == 'literal':
        return None
    if form == 'json':
        return _loads(raw)
    if form == 'jsonl':
        rows = raw.decode('utf-8').splitlines()
        if not rows or any(not row.strip() for row in rows):
            raise ValueError('complete nonempty JSONL rows required')
        return [_loads(row) for row in rows]
    raise ValueError('explicit literal, JSON or JSONL input format required')


def _encoded(file, document):
    if file['format'] == 'literal':
        return file['raw']
    if file['format'] == 'json':
        return _json_bytes(document)
    return b''.join(_json_bytes(row).replace(b'\n', b'') + b'\n' for row in document)


def _snapshot(pin, base):
    path, raw = follow._bytes(pin, base)
    return {'pin': deepcopy(pin), 'path': path, 'raw': raw, 'identity': _identity(path.stat())}


def _fresh_snapshots(snapshots, base):
    for snapshot in snapshots:
        path, raw = follow._bytes(snapshot['pin'], base)
        if path != snapshot['path'] or raw != snapshot['raw'] or _identity(path.stat()) != snapshot['identity']:
            raise ValueError('blueprint input changed across the materialization operation')


def _goal_inputs(spec, base):
    if 'goal_binding' not in spec:
        return []
    from .task_completion import binding_projection
    return deepcopy(binding_projection(spec['goal_binding'], base_dir=base)['input_pins'])


def _load(request, *, base_dir):
    cycle.ce.keys(request, {'schema_version', 'context', 'study_template', 'files', 'bindings', 'variables', 'experiment_template'})
    if type(request['schema_version']) is not int or request['schema_version'] != 1:
        raise ValueError('blueprint schema version 1 required')
    state, context = _context(follow._json(request['context'], base_dir)['cycle_root'], request['context'], base_dir)
    snapshots = [_snapshot(request['context'], base_dir), _snapshot(request['study_template'], base_dir)]
    from .agent_host import _loads, _schema
    spec = _loads(snapshots[1]['raw'])
    science.validate(spec)
    if spec['schema_version'] != 2 or spec['max_attempts'] != 1 or spec['review_policy']['policy']['max_redos'] != 0:
        raise ValueError('immutable one-attempt ordinary scientific template required')
    protected = [_snapshot(pin, base_dir) for pin in _goal_inputs(spec, snapshots[1]['path'].parent)]
    snapshots.extend(protected)
    protected_paths = {snapshot['path'] for snapshot in protected}
    rows = request['files']
    if type(rows) is not list or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError('bounded complete template input inventory required')
    files = {}
    paths = set()
    canonical = set()
    for row in rows:
        cycle.ce.keys(row, {'id', 'path', 'format', 'source'})
        cycle.ce.identity(row['id'])
        name = _relative(row['path'])
        if row['id'] == 'study' or row['id'] in files or name in paths or any(name.startswith(p + '/') or p.startswith(name + '/') for p in paths):
            raise ValueError('distinct nonoverlapping blueprint input destinations required')
        snapshot = _snapshot(row['source'], base_dir)
        if snapshot['path'] in canonical:
            raise ValueError('distinct canonical source files required')
        paths.add(name); canonical.add(snapshot['path']); snapshots.append(snapshot)
        files[row['id']] = {**deepcopy(row), 'source_path': snapshot['path'], 'raw': snapshot['raw'], 'document': _decode(snapshot['raw'], row['format'])}
    if sum(len(x['raw']) for x in snapshots) > MAX_TOTAL_BYTES:
        raise ValueError('complete blueprint snapshot exceeds declared content ceiling')
    actual = set(science.task_inputs(spec, snapshots[1]['path'].parent))
    if canonical & protected_paths:
        raise ValueError('original parent-goal dependencies are immutable; do not copy or change them')
    if actual != canonical | protected_paths:
        raise ValueError('complete mutable scientific inputs plus original immutable parent dependencies required')
    documents = {'study': spec, **{k: v['document'] for k, v in files.items() if v['format'] != 'literal'}}
    occupied = []
    bindings = request['bindings']
    if type(bindings) is not list or not bindings or len(bindings) > 128:
        raise ValueError('explicit bounded path-reference binding census required')
    for row in bindings:
        cycle.ce.keys(row, {'document', 'pointer', 'file'})
        if row['document'] not in documents or row['file'] not in files:
            raise ValueError('path binding must name an existing structured document and input file')
        tokens = _tokens(row['pointer'])
        if row['document'] == 'study' and (len(tokens) < 2 or tokens[0] != 'task'):
            raise ValueError('only scientific task references may be rebound in the study template')
        value = _pointer(documents[row['document']], row['pointer'])
        source_base = snapshots[1]['path'].parent if row['document'] == 'study' else files[row['document']]['source_path'].parent
        if type(value) is not str or science.regular(value, source_base) != files[row['file']]['source_path']:
            raise ValueError('binding must identify the exact original dependency reference')
        occupied.append((row['document'], tokens))
    variables = request['variables']
    if type(variables) is not list or not 1 <= len(variables) <= 64:
        raise ValueError('bounded declared typed experiment slots required')
    seen = set()
    for row in variables:
        cycle.ce.keys(row, {'id', 'file', 'pointer', 'schema', 'meaning', 'premise_ids'})
        cycle.ce.identity(row['id']); cycle._text(row['meaning'])
        if row['id'] in seen or row['file'] not in files or files[row['file']]['format'] == 'literal':
            raise ValueError('distinct variables require existing structured input documents')
        seen.add(row['id']); tokens = _tokens(row['pointer'])
        if type(row['premise_ids']) is not list or len(set(row['premise_ids'])) != len(row['premise_ids']):
            raise ValueError('explicit distinct premise bindings required for each input change')
        cycle._bindings(state, row['premise_ids'])
        _schema(row['schema'])
        types = row['schema']['type']
        if any(t in {'object', 'array'} for t in ([types] if type(types) is str else types)):
            raise ValueError('individual primitive input slots only; no structural or executable replacement')
        _validate_slot(_pointer(documents[row['file']], row['pointer']), row['schema'])
        occupied.append((row['file'], tokens))
    for index, (document, tokens) in enumerate(occupied):
        if any(document == d and (tokens[:len(t)] == t or t[:len(tokens)] == tokens) for d, t in occupied[:index]):
            raise ValueError('typed input slots and reference bindings cannot overlap')
    skeleton = request['experiment_template']
    cycle.ce.keys(skeleton, EXPERIMENT_FIELDS)
    cycle._vector(skeleton['cost'])
    if skeleton['cost']['wall_seconds'] < spec['max_seconds'] or skeleton['cost']['native_attempts'] != 1:
        raise ValueError('original study ceiling and counted attempt must fit the fixed experiment cost')
    required_premises = {p for v in variables for p in v['premise_ids']}
    if not required_premises <= set(skeleton['premise_ids']):
        raise ValueError('experiment must retain every declared changed-input premise')
    _fresh_snapshots(snapshots, base_dir)
    return state, context, spec, files, snapshots


def inputs(request, *, base_dir):
    """Return every actually consumed source/context input; no child process."""
    _, context, _, _, snapshots = _load(request, base_dir=base_dir)
    return _input_pins(context, snapshots, base_dir)


def _input_pins(context, snapshots, base):
    values = [{**x['pin'], 'path': str(x['path'])} for x in snapshots] + ([context['feedback_pin']] if context['feedback_pin'] is not None else [])
    return list({(str(cycle._ordinary(Path(v['path']) if Path(v['path']).is_absolute() else Path(base) / v['path'])), v['sha256']):
        {**deepcopy(v), 'path': str(cycle._ordinary(Path(v['path']) if Path(v['path']).is_absolute() else Path(base) / v['path']))} for v in values}.values())


def _write(path, raw):
    path = cycle._ordinary(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
    if follow._bytes(cycle._pin(path), path.parent)[1] != raw:
        raise ValueError('materialized output differs from compiled bytes')
    return cycle._pin(path)


def materialize(request_pin, choice_pin, *, base_dir, output_dir, presented_pins):
    """Write fresh actual inputs and a portfolio; never plan, approve or run."""
    request_snapshot = _snapshot(request_pin, base_dir)
    choice_snapshot = _snapshot(choice_pin, base_dir)
    from .agent_host import _loads
    request = _loads(request_snapshot['raw']); choice = _loads(choice_snapshot['raw'])
    state, context, original, files, snapshots = _load(request, base_dir=base_dir)
    immutable_parent_inputs = _goal_inputs(original, snapshots[1]['path'].parent)
    snapshots = [request_snapshot, choice_snapshot, *snapshots]
    if sum(len(x['raw']) for x in snapshots) > MAX_TOTAL_BYTES:
        raise ValueError('complete blueprint, choice and source snapshots exceed content ceiling')
    required = _input_pins(context, snapshots, base_dir)
    presented = {(str(cycle._ordinary(p['path'])), p['sha256']) for p in presented_pins}
    if any((str(cycle._ordinary(Path(p['path']) if Path(p['path']).is_absolute() else Path(base_dir) / p['path'])), p['sha256']) not in presented for p in required):
        raise ValueError('every source/context/choice must be a normal bound Graph input')
    cycle.ce.keys(choice, {'kind', 'blueprint_sha256', 'context_sha256', 'reason', 'variants'})
    cycle._text(choice['reason'])
    if choice['kind'] != 'research_blueprint_choice' or choice['blueprint_sha256'] != request_pin['sha256'] or choice['context_sha256'] != request['context']['sha256']:
        raise ValueError('choice must bind its exact blueprint and complete design context')
    variants = choice['variants']
    if type(variants) is not list or not 1 <= len(variants) <= 8 or len({v['id'] for v in variants}) != len(variants):
        raise ValueError('bounded distinct competing input variants required')
    out = cycle._ordinary(output_dir)
    root = cycle._ordinary(context['cycle_root'])
    if out.exists() or not out.is_relative_to(root) or out == root:
        raise ValueError('fresh materialization must remain inside its declared research cycle')
    compiled = []
    for variant in variants:
        cycle.ce.keys(variant, {'id', 'change', 'assignments', 'predictions'})
        cycle.ce.identity(variant['id']); cycle._text(variant['change'])
        if type(variant['assignments']) is not dict or set(variant['assignments']) != {v['id'] for v in request['variables']}:
            raise ValueError('complete exact declared input assignments required')
        docs = {'study': deepcopy(original), **{k: deepcopy(v['document']) for k, v in files.items() if v['format'] != 'literal'}}
        for variable in request['variables']:
            value = variant['assignments'][variable['id']]
            _validate_slot(value, variable['schema'])
            _replace(docs[variable['file']], variable['pointer'], value)
        destination = out / variant['id']
        for row in request['bindings']:
            _replace(docs[row['document']], row['pointer'], str(destination / files[row['file']]['path']))
        docs['study']['assumptions'] += ['Declared blueprint intervention ' + variable['id'] + ': ' + variable['meaning'] + '; selected literal value ' + json.dumps(variant['assignments'][variable['id']], ensure_ascii=False, allow_nan=False) for variable in request['variables']]
        science.validate(docs['study'])
        if len(_json_bytes(docs['study'])) > follow.MAX_BYTES:
            raise ValueError('complete materialized study exceeds document bound')
        payloads = {k: _encoded(v, docs.get(k)) for k, v in files.items()}
        if sum(map(len, payloads.values())) > MAX_TOTAL_BYTES or any(len(x) > follow.MAX_BYTES for x in payloads.values()):
            raise ValueError('compiled complete input population exceeds materialization bounds')
        e = {**deepcopy(request['experiment_template']), 'id': variant['id'], 'parent': context['parent_experiment'], 'change': variant['change'], 'predictions': deepcopy(variant['predictions'])}
        compiled.append((destination, docs['study'], payloads, e))
    if sum(len(_json_bytes(spec)) + sum(len(raw) for raw in payloads.values()) for _, spec, payloads, _ in compiled) > MAX_TOTAL_BYTES:
        raise ValueError('whole competing output population exceeds the aggregate materialization ceiling')
    # No prospective files exist until every assignment passes. Drift refuses
    # before writes; later failures retain partial outputs without a success claim.
    _context(root, request['context'], base_dir); _fresh_snapshots(snapshots, base_dir)
    output_pins, experiments = [], []
    for destination, spec, payloads, e in compiled:
        for identity, raw in payloads.items():
            output_pins.append(_write(destination / files[identity]['path'], raw))
        spec_pin = _write(destination / 'study.json', _json_bytes(spec)); output_pins.append(spec_pin)
        actual = set(science.task_inputs(spec, destination))
        expected = {destination / f['path'] for f in files.values()} | {
            science.regular(pin['path'], destination) for pin in _goal_inputs(spec, destination)}
        if actual != expected:
            raise ValueError('fresh task dependency closure differs from the compiled complete input population')
        e['study'] = spec_pin; experiments.append(e)
    portfolio = {'kind': 'research_portfolio', 'parent_experiment': context['parent_experiment'], 'context_sha256': request['context']['sha256'], 'reason': choice['reason'], 'experiments': experiments}
    pins = [*output_pins, *immutable_parent_inputs, request['context']] + ([context['feedback_pin']] if context['feedback_pin'] is not None else [])
    bound_portfolio(portfolio, context, proposal_base=base_dir, context_pin=request['context'], presented_pins=pins)
    portfolio_pin = _write(out / 'portfolio.json', _json_bytes(portfolio)); output_pins.append(portfolio_pin)
    _context(root, request['context'], base_dir); _fresh_snapshots(snapshots, base_dir)
    result = {'kind': 'materialized_research_blueprint', 'blueprint': {**deepcopy(request_pin), 'path': str(request_snapshot['path'])}, 'choice': {**deepcopy(choice_pin), 'path': str(choice_snapshot['path'])}, 'context': {**deepcopy(request['context']), 'path': str(snapshots[2]['path'])}, 'portfolio': portfolio_pin, 'output_pins': output_pins, 'immutable_parent_input_pins': immutable_parent_inputs, 'actual_consumed_sources': required, 'original_policy_and_resource_ceilings_preserved': True, 'all_rivals_retained': True, 'planning_approval_execution_acceptance_authorized': False, 'scientific_benefit_measured': False}
    commitment = _write(out / 'materialization.json', _json_bytes(result))
    # Recheck the original emitted pins, never recapture a changed output
    # into the success receipt. Later admission is a separate boundary.
    for emitted in [*output_pins, commitment]:
        follow._bytes(emitted, out)
    return result


def admission_spec(root, materialization_graph, *, node_id, graph_id, max_wall_seconds):
    """Build the next NORMAL portfolio tool with every new file as an input."""
    _, state = cycle._load(root)
    if str(cycle._ordinary(materialization_graph)) not in {g['root'] for g in state['graphs']}:
        raise ValueError('actual charged materialization Graph required')
    origin = cycle._graph_result(materialization_graph, node_id)
    if origin['role'] != 'designer' or origin['node_kind'] != 'tool' or origin['value'].get('kind') != 'ravel_tool_result':
        raise ValueError('ordinary completed designer tool materialization required')
    result = origin['value']['value']
    spec, _ = agent_graph._load(materialization_graph)
    node = next(n for n in spec['nodes'] if n['id'] == node_id)
    if node['action'] != 'research-blueprint' or node['max_attempts'] != 1:
        raise ValueError('completed original one-attempt blueprint compiler action required')
    if result.get('kind') != 'materialized_research_blueprint' or result['planning_approval_execution_acceptance_authorized'] is not False:
        raise ValueError('source-only compiled blueprint result required')
    _, context = _context(root, result['context'], state['base_dir'])
    pins = [*result['output_pins'], *result['immutable_parent_input_pins'], result['context']] + ([context['feedback_pin']] if context['feedback_pin'] is not None else [])
    for pin in pins:
        follow._bytes(pin, state['base_dir'])
    unique = {str(cycle._ordinary(pin['path'])): pin for pin in pins}
    inputs = [{'id': 'compiled-' + str(i), **{k: pin[k] for k in ('path', 'sha256')}} for i, pin in enumerate(unique.values())]
    ids = {p['path']: p['id'] for p in inputs}
    return {'schema_version': 1, 'graph_id': graph_id, 'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 0, 'max_wall_seconds': max_wall_seconds, 'max_reworks': 0}, 'nodes': [{'id': 'admit', 'kind': 'tool', 'role': 'designer', 'depends_on': [], 'inputs': inputs, 'packet': None, 'action': 'research-portfolio', 'max_attempts': 1, 'parameters': {'proposal_input': ids[result['portfolio']['path']], 'context_input': ids[result['context']['path']]}}]}


def choice_spec(request_pin, *, base_dir, graph_id, model, reasoning_effort, max_output_tokens, max_wall_seconds, adapter='responses'):
    """One ordinary designer model node with the actual finite slot schema."""
    request = follow._json(request_pin, base_dir)
    state, context, _, _, snapshots = _load(request, base_dir=base_dir)
    cycle._text(model); cycle._text(reasoning_effort)
    if adapter not in provider_transport.MODEL_ACTIONS or type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000 or type(max_wall_seconds) is not int or not 1 <= max_wall_seconds <= 3600:
        raise ValueError('explicit bounded ordinary designer model adapter required')
    labels = list(request['experiment_template']['observable']['outcomes'])
    active = [h['id'] for h in state['hypotheses'] if cycle._fresh(state, h['premise_bindings'])]
    def obj(properties):
        return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}
    schema = obj({'kind': {'type': 'string', 'const': 'research_blueprint_choice'},
        'blueprint_sha256': {'type': 'string', 'const': request_pin['sha256']},
        'context_sha256': {'type': 'string', 'const': request['context']['sha256']},
        'reason': {'type': 'string'}, 'variants': {'type': 'array', 'minItems': 1, 'maxItems': 8,
            'items': obj({'id': {'type': 'string'}, 'change': {'type': 'string'},
                'assignments': obj({v['id']: deepcopy(v['schema']) for v in request['variables']}),
                'predictions': obj({identity: {'type': ['string', 'null'], 'enum': labels + [None]} for identity in active})})}})
    pins = [request_pin, *_input_pins(context, snapshots, base_dir)]
    pins = list({str(cycle._ordinary(Path(p['path']) if Path(p['path']).is_absolute() else Path(base_dir) / p['path'])): p for p in pins}.values())
    normal = [{'id': 'blueprint-' + str(i), 'path': str(cycle._ordinary(Path(p['path']) if Path(p['path']).is_absolute() else Path(base_dir) / p['path'])), 'sha256': p['sha256']} for i, p in enumerate(pins)]
    return {'schema_version': 1, 'graph_id': graph_id,
        'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': max_output_tokens, 'max_wall_seconds': max_wall_seconds, 'max_reworks': 0},
        'nodes': [{'id': 'choose', 'kind': 'model', 'role': 'designer', 'depends_on': [], 'inputs': normal,
            'packet': None, 'action': adapter, 'max_attempts': 1,
            'parameters': {'instructions': 'Use the complete original role feedback, both actual rival sets and supplied scientific template. Choose useful competing interventions using ONLY the declared typed input slots. Preserve original source, policy, resource ceilings and the whole task. Predict each current rival or declare it unknown. Do not supply guessed scientific outputs, alter adapter code or imply execution approval.',
                'model': model, 'reasoning_effort': reasoning_effort, 'max_output_tokens': max_output_tokens, 'output_schema': schema}}]}


def prepare_choice(root, graph_root, *, node_id, request_pin, base_dir, output_dir):
    """Persist an actual charged designer result; never invent model genealogy."""
    _, state = cycle._load(root)
    if str(cycle._ordinary(graph_root)) not in {g['root'] for g in state['graphs']}:
        raise ValueError('designer must use the existing cumulative Graph ledger')
    origin = cycle._graph_result(graph_root, node_id)
    if origin['role'] != 'designer' or origin['node_kind'] != 'model' or origin['value'].get('kind') != 'model_result':
        raise ValueError('completed actual designer model result required')
    actual, _ = agent_graph._load(graph_root)
    node = next(n for n in actual['nodes'] if n['id'] == node_id)
    expected = choice_spec(request_pin, base_dir=base_dir, graph_id=actual['graph_id'],
        model=node['parameters']['model'], reasoning_effort=node['parameters']['reasoning_effort'],
        max_output_tokens=node['parameters']['max_output_tokens'], max_wall_seconds=actual['budget']['max_wall_seconds'], adapter=node['action'])
    if actual != expected or node_id != 'choose':
        raise ValueError('designer must receive the exact full current blueprint, rival context and finite schema')
    request = follow._json(request_pin, base_dir)
    if request['context'] is None or follow._json(request['context'], base_dir)['cycle_root'] != str(cycle._ordinary(root)):
        raise ValueError('designer choice belongs to another research cycle')
    out = cycle._ordinary(output_dir)
    if out.exists() or not out.is_relative_to(cycle._ordinary(root)) or out == cycle._ordinary(root):
        raise ValueError('fresh generated-choice destination within the cycle required')
    choice = origin['value']['value']
    pin = _write(out / 'choice.json', _json_bytes(choice))
    provenance = {'kind': 'actual_designer_blueprint_choice', 'origin': origin, 'request': deepcopy(request_pin),
        'choice': pin, 'source_or_control_transport': 'retain original model_result execution_observation; no inferred provider qualification',
        'experiment_execution_authorized': False}
    proof = _write(out / 'provenance.json', _json_bytes(provenance))
    return {'choice': pin, 'provenance': proof}
