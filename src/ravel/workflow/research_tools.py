"""Connect task-directed APIs, experiment planning and ordinary tool handoffs.

This module composes the existing context compiler, finite blueprint compiler,
AgentGraph, research journal, science lifecycle and feedback reader. It has no
scheduler, acceptance state, installer or implicit provider. A supplied choice
needs no model turn. An optional designer uses the same cumulative Graph budget.
"""
import argparse
import ast
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path

from . import agent_graph, research_blueprint as blueprint, research_cycle as cycle
from . import research_followup as follow, science, scientific_context as context


def _pin2(pin):
    return {k: pin[k] for k in ('path', 'sha256')}


def _unique(pins, base):
    result = {}
    for pin in pins:
        path, _ = follow._bytes(pin, base)
        row = {**pin, 'path': str(path)}
        if str(path) in result and result[str(path)] != row:
            raise ValueError('conflicting research-tool source identity')
        result[str(path)] = row
    if len(result) > 128:
        raise ValueError('complete context/tool closure exceeds normal Graph input ceiling')
    return list(result.values())


def _write(path, value):
    return blueprint._write(path, blueprint._json_bytes(value))


def _json_commitment(path, value):
    raw = blueprint._json_bytes(value)
    return {'path': str(cycle._ordinary(path)), 'sha256': hashlib.sha256(raw).hexdigest(),
            'size': len(raw)}


def _generated_population(root, pins):
    """Check the complete generated tree against the original emitted paths."""
    root = cycle._ordinary(root)
    files = {cycle._ordinary(pin['path']) for pin in pins}
    if any(not path.is_relative_to(root) or path == root for path in files):
        raise ValueError('generated research-tool output escaped its fresh directory')
    directories = {parent for path in files for parent in path.parents
                   if parent.is_relative_to(root) and parent != root}
    actual_files, actual_directories = set(), set()
    for path in root.rglob('*'):
        path = cycle._ordinary(path)
        if path.is_file():
            actual_files.add(path)
        elif path.is_dir():
            actual_directories.add(path)
        else:
            raise ValueError('ordinary generated research-tool files and directories required')
    if actual_files != files or actual_directories != directories:
        raise ValueError('complete generated research-tool output membership changed')


def _destination(root, output_dir):
    raw = Path(output_dir)
    if '..' in raw.parts:
        raise ValueError('fresh destination may not contain parent traversal')
    out = cycle._ordinary(raw)
    parent = cycle._ordinary(root)
    if (parent.resolve(strict=True) != parent or out.resolve(strict=False) != out
            or out.exists() or not out.is_relative_to(parent) or out == parent):
        raise ValueError('fresh canonical destination within the existing cycle required')
    return out


def _adapter_documents(spec):
    # Resolution imports the existing admitted adapter, never supplied source.
    # It calls no scientific method, backend, runtime probe or installer.
    if spec['mode'] == 'quantities':
        from ravel.physics import quantities
        adapter = quantities
    else:
        adapter = science.adapter(spec)
    documents, queries = [], []
    for identity, module, wanted in (
            ('ordinary-adapter', adapter, ('validate', 'inputs', 'run', 'calculate')),
            ('ordinary-lifecycle', science, ('task_inputs', 'plan', 'run'))):
        pin = cycle._pin(inspect.getsourcefile(module))
        definitions = {node.name for node in ast.parse(follow._bytes(pin, Path(pin['path']).parent)[1]).body
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        documents.append({'id': identity, 'pin': _pin2(pin), 'language': 'python', 'role': 'api',
            'version': 'Exact ordinary source SHA256 ' + pin['sha256'], 'dependencies': []})
        for name in wanted:
            if name in definitions:
                queries.append({'id': identity + '-' + name, 'symbol': name, 'mode': 'definition',
                    'documents': [identity], 'required': True})
    return documents, queries


def _research_facts(state):
    """Expose current full premise/knowledge context through the same kernel."""
    premises = deepcopy(state['premises'])
    contexts = [row.get('knowledge_context') for row in premises]
    knowledge, pins = [], [pin for row in premises for pin in row['basis']]
    for binding in state.get('knowledge_bindings', []):
        matched = {'request_sha256': binding['packet']['request_sha256'],
                   'packet_sha256': cycle.ce.digest(binding['packet'])}
        if any({**matched, 'premise_id': source} in contexts for source in binding['premise_map']):
            knowledge.append({'packet': deepcopy(binding['packet']), 'premise_map': deepcopy(binding['premise_map']),
                'source_assertions_only': True, 'scientific_acceptance': False})
            pins.extend([binding['request'], *binding['dependencies']])
    return {'premises': premises, 'knowledge_contexts': knowledge}, pins


def prepare_model_proposals(root, request_pin, *, premise_map, reason):
    """Bind typed structural proposals into the existing ordinary design context.

    Called after any selecting Graph releases the campaign lock. Complete
    selected premise mapping, current source closure, reopening and budgets
    retain their original research_cycle laws. Field similarity grants no vote.
    """
    from . import physics_knowledge
    _, state = cycle._load(root)
    request = follow._json(request_pin, state['base_dir'])
    if type(request) is not dict or type(request.get('schema_version')) is not int or request['schema_version'] != 2:
        raise ValueError('explicit typed structural physics-knowledge request/v2 required')
    packet = physics_knowledge.retrieve(request, state['base_dir'])
    if packet.get('structural_models', {}).get('kind') != 'structural-model-proposals':
        raise ValueError('complete structural model proposal context required')
    return cycle.bind_knowledge(root, request_pin, premise_map=premise_map, reason=reason)


def retrieve_literature(broker, operation, arguments):
    """A controller step uses its admitted attempt broker, never a provider directly."""
    from . import literature_serving
    reply = literature_serving.call(broker, operation, arguments)
    return reply, (literature_serving.load(broker.rundir, reply) if reply['status'] == 'ok' else None)


def prepare_literature_context(root, request_pin, output_dir, *, premise_map=None, reason):
    """Prepare complete located sources after the selecting Graph releases its lock.

    Missing bibliography/extraction remains a useful intermediate writing input.
    Optional complete selected premise mapping uses the existing bind_knowledge;
    no source or generated summary is promoted to scientific acceptance.
    """
    from . import literature_context
    _, state = cycle._load(root)
    request = follow._json(request_pin, state['base_dir'])
    expected = {'root': str(cycle._ordinary(root)), 'contract_sha256': cycle.ce.digest(state['contract'])}
    if request.get('cycle_binding') != expected:
        raise ValueError('literature preparation must retain its complete original campaign contract')
    cycle._text(reason)
    out = _destination(root, output_dir)
    result = literature_context.prepare(request_pin, out, base_dir=state['base_dir'])
    if premise_map is not None:
        if result['knowledge_request'] is None:
            raise ValueError('missing literature cannot supply scientific premises')
        cycle.bind_knowledge(root, result['knowledge_request'], premise_map=premise_map, reason=reason)
    return literature_context.consume(result['product'], base_dir=state['base_dir'])


def extract_literature_pdf(root, request_pin, output_dir, host, *, max_wall_seconds):
    """One ordinary campaign-charged PDF tool; no independent execution loop."""
    return _literature_tool(root, request_pin, output_dir, host, max_wall_seconds, 'pdf')


def acquire_literature(root, request_pin, output_dir, host, *, max_wall_seconds):
    """One explicitly configured public-source GET through the ordinary Host."""
    return _literature_tool(root, request_pin, output_dir, host, max_wall_seconds, 'acquire')


def discover_literature(root, request_pin, output_dir, host, *, max_wall_seconds):
    """Typed query or explicit record lookup through the original charged GET."""
    from . import literature_discovery
    return literature_discovery.execute(root, request_pin, output_dir, host,
        max_wall_seconds=max_wall_seconds)


def prepare_discovered_sources(root, product_pin, output_dir, *, reason):
    """Secondary metadata to ordinary located context and writer citation fields."""
    from . import literature_discovery
    return literature_discovery.prepare_sources(root, product_pin, output_dir, reason=reason)


def _literature_tool(root, request_pin, output_dir, host, max_wall_seconds, kind):
    from . import literature_context
    _, state = cycle._load(root)
    reader = literature_context._Reader(state['base_dir'])
    if kind == 'pdf':
        _, request, _ = literature_context._pdf_request(request_pin, reader)
        pins = literature_context.pdf_inputs(request_pin, base_dir=state['base_dir'])
        action, node_id, destination, binding_kind = 'literature-pdf-extract', 'extract', 'extraction', 'ordinary-literature-pdf-binding'
    elif kind == 'acquire':
        _, request = literature_context._acquisition_request(request_pin, reader)
        pins = literature_context.acquisition_inputs(request_pin, base_dir=state['base_dir'])
        action, node_id, destination, binding_kind = 'literature-acquire', 'acquire', 'acquisition', 'ordinary-literature-acquisition-binding'
    else:
        raise ValueError('finite ordinary literature service required')
    if request['max_seconds'] > max_wall_seconds:
        raise ValueError('literature tool must fit the original selected Graph allowance')
    out = _destination(root, output_dir); out.mkdir()
    # PDF originals use the existing 64MiB artifact policy, not the 2MiB
    # research_followup JSON/text reader used by _unique.
    if len(pins) > 128 or len({p['path'] for p in pins}) != len(pins):
        raise ValueError('complete literature source closure exceeds ordinary Graph input policy')
    rows = [{'id':'source-'+str(i), **_pin2(pin)} for i,pin in enumerate(pins)]
    request_path = str(cycle._ordinary(request_pin['path'] if Path(request_pin['path']).is_absolute() else Path(state['base_dir'])/request_pin['path']))
    request_id = next(row['id'] for row in rows if row['path'] == request_path)
    spec = _tool_spec('literature-'+kind+'-'+cycle.ce.digest(request)[:16], action, rows,
        {'request_input':request_id,'output_dir':str(out/destination)}, max_wall_seconds, node_id=node_id)
    spec['nodes'][0]['role']='executor'
    graph_root=out/'graph'
    # The ordinary campaign API inherits the original parent binding, creates
    # the fresh Graph, reserves/charges, executes and records its actual outcome.
    cycle.execute_graph(root,graph_root,spec,host)
    origin=cycle._graph_result(graph_root,node_id)
    value=origin['value']
    if value.get('kind')!='ravel_tool_result' or value.get('action')!=action:
        raise ValueError('actual ordinary literature tool result required')
    binding={'schema_version':1,'kind':binding_kind,'graph':str(graph_root),
             'node':node_id,'origin':origin,'product':value['value']['product']}
    path=out/'binding.json';expected=_json_commitment(path,binding)
    if _write(path,deepcopy(binding))!=expected:
        raise ValueError('literature binding differs from its intended emitted bytes')
    reader.finish()
    # Empty/unreadable pages are valid unresolved products; a failed whole PDF
    # remains an actual failed tool outcome and cannot enter located knowledge.
    actual = (literature_context.consume_pdf(expected, base_dir=state['base_dir']) if kind == 'pdf'
              else literature_context.consume_acquisition(expected, base_dir=state['base_dir']))
    result={'binding':expected,'product':deepcopy(binding['product']), 'status':actual['status'],
            'claims':deepcopy(literature_context.FLAGS)}
    if kind == 'pdf':result['page_count']=actual['page_count']
    else:result['source_artifact']=deepcopy(actual['source_artifact'])
    cycle._check_pin(expected,state['base_dir'])
    if cycle._graph_result(graph_root,node_id)!=origin:
        raise ValueError('literature tool receipt changed before public return')
    return deepcopy(result)


def prepare(root, blueprint_pin, output_dir, *, api_documents=(), queries=()):
    """Bind the full task and real adapter/lifecycle APIs to a concrete design.

    Additional source/procedure/failure documents are explicit source pins. A
    missing query stays visible and testable; it does not veto an exploratory
    design. Existing source/context ceilings and the original quantity census
    remain authoritative. Use a fresh explicit contract to change a ceiling.
    """
    _, state = cycle._load(root)
    base = state['base_dir']
    request = follow._json(blueprint_pin, base)
    _, current, spec, _, _ = blueprint._load(request, base_dir=base)
    if current['cycle_root'] != str(cycle._ordinary(root)):
        raise ValueError('tool design belongs to another research cycle')
    original = deepcopy(state['context']['request'])
    docs, auto_queries = _adapter_documents(spec)
    original['api_documents'].extend(docs + deepcopy(list(api_documents)))
    original['queries'].extend(auto_queries + deepcopy(list(queries)))
    compiled = context.compile_context(original, Path(base))
    facts, knowledge_pins = _research_facts(state)
    pins = [blueprint_pin, *blueprint.inputs(request, base_dir=base),
            cycle._pin(__file__), cycle._pin(context.__file__)]
    pins.extend(cycle._pin(row['path']) for row in context.input_pins(original, Path(base)))
    pins = _unique([*pins, *knowledge_pins], base)
    out = _destination(root, output_dir)
    request_pin = _write(out / 'api-request.json', original)
    context_pin = _write(out / 'api-context.json', compiled)
    bundle = {'schema_version': 1, 'kind': 'research_tool_context', 'cycle_root': str(cycle._ordinary(root)),
        'blueprint': deepcopy(blueprint_pin), 'design_context': deepcopy(request['context']),
        'api_request': request_pin, 'api_context': context_pin,
        'source_inputs': pins, 'task': original['task'], 'requested_quantities': original['requested_quantities'],
        'compatibility_groups': original['compatibility_groups'], 'question': state['contract']['question'],
        'scope': state['contract']['scope'], 'goal_binding': deepcopy(state['contract'].get('goal_binding')),
        'study_mode': spec['mode'], 'context_complete': compiled['context_complete'],
        'missing_and_omitted': deepcopy(compiled['omissions']), 'research_facts': facts,
        'execution_authorized': False, 'physics_validated': False}
    pin = _write(out / 'bundle.json', bundle)
    check_binding(pin, base, state=state)
    return pin


def check_binding(pin, base, *, state=None):
    """Recheck consumed context at every contributing design/use boundary.

    The existing journal has no recursive tool-binding load. Historical
    artifacts remain immutable; this checks a contributing current design.
    """
    bundle = follow._json(pin, base)
    cycle.ce.keys(bundle, {'schema_version', 'kind', 'cycle_root', 'blueprint', 'design_context',
        'api_request', 'api_context', 'source_inputs', 'task', 'requested_quantities',
        'compatibility_groups', 'question', 'scope', 'goal_binding', 'study_mode',
        'context_complete', 'missing_and_omitted', 'research_facts', 'execution_authorized', 'physics_validated'})
    if bundle.get('kind') != 'research_tool_context' or bundle.get('schema_version') != 1:
        raise ValueError('bound research tool context required')
    original = follow._json(bundle['api_request'], base)
    compiled = follow._json(bundle['api_context'], base)
    request = follow._json(bundle['blueprint'], base)
    actual_state, design, spec, _, _ = blueprint._load(request, base_dir=base)
    if bundle['cycle_root'] != design['cycle_root'] or bundle['design_context'] != request['context']:
        raise ValueError('exact current blueprint context required')
    if state is None:
        state = actual_state
    docs, queries = _adapter_documents(spec)
    initial = state['context']['request']
    for key in initial:
        if key not in {'api_documents', 'queries'} and original[key] != initial[key]:
            raise ValueError('original task/context limits must remain literal')
    for key, added in (('api_documents', docs), ('queries', queries)):
        fixed = initial[key] + added
        if original[key][:len(fixed)] != fixed:
            raise ValueError('actual adapter APIs and original context must remain in the source corpus')
    expected = [bundle['blueprint'], *blueprint.inputs(request, base_dir=base),
        cycle._pin(__file__), cycle._pin(context.__file__)]
    expected += [cycle._pin(row['path']) for row in context.input_pins(original, Path(base))]
    facts, knowledge_pins = _research_facts(state)
    expected.extend(knowledge_pins)
    if bundle['research_facts'] != facts:
        raise ValueError('complete current premise/domain/convention/knowledge context required')
    if _unique(expected, base) != bundle['source_inputs'] or bundle['study_mode'] != spec['mode']:
        raise ValueError('complete original and tool API source population required')
    required = [pin, bundle['api_request'], bundle['api_context'], *bundle['source_inputs']]
    _unique(required, base)
    if context.compile_context(original, Path(base)) != compiled:
        raise ValueError('consumed scientific API context changed')
    if (bundle['task'] != original['task'] or bundle['requested_quantities'] != original['requested_quantities']
            or bundle['compatibility_groups'] != original['compatibility_groups']
            or bundle['context_complete'] != compiled['context_complete']
            or bundle['missing_and_omitted'] != compiled['omissions']
            or bundle['execution_authorized'] is not False or bundle['physics_validated'] is not False):
        raise ValueError('tool context may not narrow the task or confer scientific authority')
    if state is not None and (bundle['question'] != state['contract']['question']
            or bundle['scope'] != state['contract']['scope']
            or bundle['task'] != state['context']['request']['task']
            or bundle['requested_quantities'] != state['context']['requested_quantities']
            or bundle['compatibility_groups'] != state['context']['compatibility_groups']
            or bundle['goal_binding'] != state['contract'].get('goal_binding')):
        raise ValueError('tool context must retain the current whole task and parent assignment')
    return bundle


def _current(pin, base):
    bundle = check_binding(pin, base)
    _, state = cycle._load(bundle['cycle_root'])
    check_binding(pin, base, state=state)
    blueprint._context(bundle['cycle_root'], bundle['design_context'], base)
    return bundle


def input_pins(bundle_pin, base):
    bundle = _current(bundle_pin, base)
    return _unique([bundle_pin, bundle['api_request'], bundle['api_context'], *bundle['source_inputs']], base)


def choice_spec(bundle_pin, *, base_dir, **parameters):
    """Present exact task-directed APIs to the existing typed designer schema."""
    bundle = _current(bundle_pin, base_dir)
    spec = blueprint.choice_spec(bundle['blueprint'], base_dir=base_dir, **parameters)
    rows = spec['nodes'][0]['inputs']
    old = {row['path'] for row in rows}
    for pin in input_pins(bundle_pin, base_dir):
        if pin['path'] not in old:
            rows.append({'id': 'tool-source-' + str(len(rows)), **_pin2(pin)})
            old.add(pin['path'])
    if len(rows) > 128:
        raise ValueError('complete designer context exceeds normal Graph input ceiling')
    spec['nodes'][0]['parameters']['instructions'] += (
        ' The bound api-context contains actual source definitions, explicit missing APIs and original'
        ' requested quantities. Use it to plan an executable tool intervention; missing evidence remains'
        ' a question to test. A code exit or backend completion flag cannot complete the scientific task.'
        ' Preserve source/runtime restrictions and provide a constructive recovery when a tool is absent.')
    return spec


def prepare_choice(root, graph_root, *, node_id, bundle_pin, base_dir, output_dir):
    bundle = _current(bundle_pin, base_dir)
    _, state = cycle._load(root)
    if (bundle['cycle_root'] != str(cycle._ordinary(root))
            or str(cycle._ordinary(graph_root)) not in {g['root'] for g in state['graphs']}):
        raise ValueError('actual charged designer belongs to another cycle')
    origin = cycle._graph_result(graph_root, node_id)
    actual, _ = agent_graph._load(graph_root)
    node = next(row for row in actual['nodes'] if row['id'] == node_id)
    if origin['role'] != 'designer' or origin['node_kind'] != 'model' or origin['value'].get('kind') != 'model_result':
        raise ValueError('completed ordinary designer model result required')
    expected = choice_spec(bundle_pin, base_dir=base_dir, graph_id=actual['graph_id'],
        model=node['parameters']['model'], reasoning_effort=node['parameters']['reasoning_effort'],
        max_output_tokens=node['parameters']['max_output_tokens'], max_wall_seconds=actual['budget']['max_wall_seconds'], adapter=node['action'])
    if 'goal_binding' in state['contract']:
        expected['goal_binding'] = deepcopy(state['contract']['goal_binding'])
    if actual != expected or node_id != 'choose':
        raise ValueError('designer did not receive the complete bound API/tool context')
    out = _destination(root, output_dir)
    choice = _write(out / 'choice.json', origin['value']['value'])
    proof = _write(out / 'provenance.json', {'kind': 'actual_tool_context_choice', 'bundle': bundle_pin,
        'origin': origin, 'choice': choice, 'execution_authorized': False})
    _current(bundle_pin, base_dir)
    return {'choice': choice, 'provenance': proof}


def _tool_spec(graph_id, action, inputs, parameters, wall, *, node_id):
    if type(wall) is not int or not 1 <= wall <= 86400:
        raise ValueError('explicit bounded ordinary tool wall ceiling required')
    return {'schema_version': 1, 'graph_id': graph_id,
        'budget': {'max_nodes': 1, 'max_calls': 1, 'max_output_tokens': 0, 'max_wall_seconds': wall, 'max_reworks': 0},
        'nodes': [{'id': node_id, 'kind': 'tool', 'role': 'designer', 'depends_on': [], 'inputs': inputs,
            'packet': None, 'action': action, 'max_attempts': 1, 'parameters': parameters}]}


def materialization_spec(bundle_pin, choice_pin, *, base_dir, output_dir, graph_id, max_wall_seconds):
    bundle = _current(bundle_pin, base_dir)
    output_dir = _destination(bundle['cycle_root'], output_dir)
    pins = _unique([*input_pins(bundle_pin, base_dir), choice_pin], base_dir)
    rows = [{'id': 'tool-' + str(i), **_pin2(pin)} for i, pin in enumerate(pins)]
    ids = {row['path']: row['id'] for row in rows}
    return _tool_spec(graph_id, 'research-tools', rows,
        {'bundle_input': ids[str(cycle._ordinary(bundle_pin['path']))],
         'choice_input': ids[str(cycle._ordinary(choice_pin['path']))], 'output_dir': str(output_dir)},
        max_wall_seconds, node_id='compile')


def materialize(bundle_pin, choice_pin, *, base_dir, output_dir, presented_pins):
    bundle = _current(bundle_pin, base_dir)
    output_dir = _destination(bundle['cycle_root'], output_dir)
    required = _unique([*input_pins(bundle_pin, base_dir), choice_pin], base_dir)
    snapshots = [blueprint._snapshot(pin, base_dir) for pin in required]
    presented = {(str(cycle._ordinary(row['path'])), row['sha256']) for row in presented_pins}
    if any((row['path'], row['sha256']) not in presented for row in required):
        raise ValueError('all consumed task/API/choice sources must be actual Graph inputs')
    original = blueprint.materialize(bundle['blueprint'], choice_pin, base_dir=base_dir,
        output_dir=output_dir, presented_pins=presented_pins)
    blueprint._fresh_snapshots(snapshots, base_dir)
    original_commitment = _json_commitment(Path(output_dir) / 'materialization.json', original)
    emitted = [*original['output_pins'], original_commitment]
    output_snapshots = [blueprint._snapshot(pin, base_dir) for pin in emitted]
    portfolio = follow._json(original['portfolio'], base_dir)
    for experiment in portfolio['experiments']:
        experiment['tool_context'] = deepcopy(bundle_pin)
    expected_portfolio = _json_commitment(Path(output_dir) / 'tool-portfolio.json', portfolio)
    new_portfolio = _write(Path(output_dir) / 'tool-portfolio.json', portfolio)
    if new_portfolio != expected_portfolio:
        raise ValueError('research-tool portfolio differs from the emitted JSON commitment')
    emitted.append(expected_portfolio)
    output_snapshots.append(blueprint._snapshot(expected_portfolio, base_dir))
    pins = [*original['output_pins'], *original['immutable_parent_input_pins'], *required, new_portfolio]
    result = {'kind': 'materialized_research_tools', 'bundle': bundle_pin, 'context': original['context'],
        'portfolio': new_portfolio, 'output_pins': _unique(pins, base_dir),
        'materialization': original, 'execution_authorized': False, 'physics_validated': False}
    _current(bundle_pin, base_dir)
    expected_receipt = _json_commitment(Path(output_dir) / 'tool-materialization.json', result)
    receipt = _write(Path(output_dir) / 'tool-materialization.json', result)
    if receipt != expected_receipt:
        raise ValueError('research-tool receipt differs from the emitted JSON commitment')
    emitted.append(expected_receipt)
    output_snapshots.append(blueprint._snapshot(expected_receipt, base_dir))
    blueprint._fresh_snapshots(snapshots, base_dir)
    _current(bundle_pin, base_dir)
    blueprint._fresh_snapshots(output_snapshots, base_dir)
    _generated_population(output_dir, emitted)
    return result


def admission_spec(root, graph_root, *, node_id, graph_id, max_wall_seconds):
    _, state = cycle._load(root)
    if str(cycle._ordinary(graph_root)) not in {g['root'] for g in state['graphs']}:
        raise ValueError('actual cumulatively charged tool materialization required')
    origin = cycle._graph_result(graph_root, node_id)
    spec, _ = agent_graph._load(graph_root)
    node = next(row for row in spec['nodes'] if row['id'] == node_id)
    if (origin['role'] != 'designer' or origin['node_kind'] != 'tool'
            or node['action'] != 'research-tools' or node['max_attempts'] != 1
            or origin['value'].get('kind') != 'ravel_tool_result'):
        raise ValueError('ordinary completed one-attempt tool compiler required')
    result = origin['value']['value']
    if result.get('kind') != 'materialized_research_tools' or result['execution_authorized'] is not False:
        raise ValueError('unapproved source-bound tool materialization required')
    _current(result['bundle'], state['base_dir'])
    pins = _unique(result['output_pins'], state['base_dir'])
    rows = [{'id': 'admitted-' + str(i), **_pin2(pin)} for i, pin in enumerate(pins)]
    ids = {row['path']: row['id'] for row in rows}
    return _tool_spec(graph_id, 'research-portfolio', rows,
        {'proposal_input': ids[result['portfolio']['path']], 'context_input': ids[result['context']['path']]},
        max_wall_seconds, node_id='admit')


def plan(root, identity, rundir):
    """The actual ordinary plan and reservation; no proxy approval or runner."""
    return cycle.prepare_experiment(root, identity, rundir)


def plan_workflow(root, blueprint_pin, choice_pin, output_dir, rundir, *,
                  max_wall_seconds, api_documents=(), queries=()):
    """Default durable source/design/admission/selection/ordinary-plan subgraph.

    A concrete supplied choice still needs no model call. A framework checkpoint
    never approves the study or replaces the current source/campaign ledger.
    """
    from .research_orchestrator import design
    return design(root, blueprint_pin, choice_pin, output_dir, rundir,
        max_wall_seconds=max_wall_seconds, api_documents=api_documents, queries=queries)


def routine_operations():
    """Public coordinator operations for an absent or reusable analysis routine.

    The stateful research coordinator chooses a source-bound operation after
    inspecting the original task. No literal keyword supplies physics authority.
    Generation must run outside an executing campaign Graph: that Graph owns
    the campaign lock, and each original role is charged as its own child.
    """
    return {'paper_first':{'entrypoint':'research_tools.routine_workflow',
        'choice':{'kind':'paper-first','request':'exact complete preparation request pin'},
        'requires':['original goal-bound campaign','complete paper/HEPData/source inputs','finite original role budget','configured Host']},
        'reuse':{'entrypoint':'research_tools.routine_workflow',
            'choice':{'kind':'existing-source','specification':'exact existing ordinary source/build/event specification pin'}},
        'generation_after_checks_approval':{'entrypoint':'research_tools.routine_step','actions':['generate'],
            'requires':'a recorded approval of the request\'s declared construction checks (agentrivet-construction approve-checks)'},
        'feedback_and_completion':{'entrypoint':'research_tools.routine_step',
            'actions':['prepare-build','prepare-events','repair','close'],
            'requires':'current ordinary source/build/event or failure/review evidence, original assignment and independent final delivery gate'},
        'new_scheduler':False,'execution_authorized':False,'physics_validated':False}


def routine_workflow(root, choice_pin, output_dir, host, *, max_wall_seconds):
    """Coordinator-selected paper -> original roles -> ordinary source handoff.

    This is an invocable planner operation, not a supplied hand-authored Graph.
    It constructs the preparation Graph itself and then uses the stable charged
    executor for every original role call. Native admission/approval/run remains
    with the ordinary research/lifecycle services. Existing source reuse makes
    no new generation calls and retains its exact source specification.
    """
    from . import agentrivet_construction as construction
    _,state=cycle._load(root);base=state['base_dir'];choice=follow._json(choice_pin,base)
    if choice.get('kind')=='existing-source':
        cycle.ce.keys(choice,{'kind','specification'})
        spec=construction._document(choice['specification'],base)[1];science.validate(spec)
        if (spec['mode']!='analyze' or spec['task']['backend'] not in {'agentrivet-source','routine-build','rivet-built'}
                or spec.get('goal_binding')!=state['contract'].get('goal_binding') or 'goal_binding' not in spec):
            raise ValueError('existing ordinary routine source must preserve the original assignment')
        follow._bytes(choice_pin,base)
        return {'kind':'existing-routine-research-handoff','specification':choice['specification'],
            'goal_binding':deepcopy(spec['goal_binding']),'generation_calls':0,
            'execution_authorized':False,'physics_validated':False}
    cycle.ce.keys(choice,{'kind','request'})
    if choice['kind']!='paper-first':raise ValueError('explicit routine operation choice required')
    request=construction._document(choice['request'],base)[1]
    if str(construction._path(request['campaign'],base))!=str(cycle._ordinary(root)):
        raise ValueError('construction belongs to another original campaign')
    out=_destination(root,output_dir)
    pins=[];seen={}
    for reference in [_pin2(choice_pin),choice['request'],*construction.input_pins(request,base),_pin2(cycle._pin(__file__))]:
        path,_=construction._bytes(reference,base)
        if str(path) in seen and seen[str(path)]!=reference['sha256']:
            raise ValueError('conflicting original routine operation source identity')
        if str(path) not in seen:pins.append({'path':str(path),'sha256':reference['sha256']})
        seen[str(path)]=reference['sha256']
    if len(pins)>128:raise ValueError('complete routine preparation exceeds ordinary Graph input population')
    rows=[{'id':'routine-'+str(i),**_pin2(pin)} for i,pin in enumerate(pins)]
    identities={row['path']:row['id'] for row in rows}
    graph=out/'preparation-graph'
    spec=_tool_spec('routine-source-preparation','agentrivet-prepare',rows,
        {'request_input':identities[str(construction._path(choice['request']['path'],base))],
         'output_directory':str(out/'construction')},max_wall_seconds,node_id='prepare')
    observed=cycle.execute_graph(root,graph,spec,host)
    if not observed['complete']:raise ValueError('ordinary routine preparation failed; retain its charged Graph')
    origin=cycle._graph_result(graph,'prepare')['value']
    if origin.get('kind')!='ravel_tool_result' or origin.get('action')!='agentrivet-prepare':
        raise ValueError('actual ordinary source preparation result required')
    request_pin=origin['value']['request']
    _,prepared=construction._load(request_pin,base)
    if (prepared.get('construction') or {}).get('checks') is not None and not (Path(request_pin['path']).parent/'checks-approval.json').exists():
        # Declared construction checks launch native tools: they wait for their approval.
        follow._bytes(choice_pin,base)
        handoff={'kind':'paper-first-routine-awaiting-checks-approval','choice':choice_pin,'preparation_graph':str(graph),
            'request':request_pin,'goal_binding':deepcopy(prepared['goal_binding']),'operations':routine_operations(),
            'next_operation':'Record the checks approval with agentrivet-construction approve-checks, then select routine_step action generate.',
            'generation_calls':0,'execution_authorized':False,'physics_validated':False}
        construction._emit(out/'routine-handoff.json',handoff)
        return handoff
    return _routine_generation(root,choice_pin,graph,request_pin,base,host,out)


def _routine_generation(root, choice_pin, graph, request_pin, base, host, out):
    from . import agentrivet_construction as construction
    generation=construction.generate(request_pin,base_dir=base,host=host)
    _,prepared=construction._load(request_pin,base);_,result,_=construction._generation(prepared,generation,base)
    if choice_pin is not None:follow._bytes(choice_pin,base)
    out.mkdir(parents=True,exist_ok=True)
    handoff={'kind':'paper-first-routine-research-handoff','choice':choice_pin,'preparation_graph':None if graph is None else str(graph),
        'request':request_pin,'generation':generation,'specification':result['source_study']['specification'],
        'goal_binding':deepcopy(prepared['goal_binding']),'operations':routine_operations(),
        'next_operation':'Admit and plan the generated ordinary source specification with the existing research portfolio and lifecycle; then use routine_step for observed build/events/feedback/closure.',
        'upstream_reviews_carried':[],'execution_authorized':False,'physics_validated':False}
    construction._emit(out/'routine-handoff.json',handoff)
    return handoff


def routine_step(root, selection_pin, *, base_dir, host=None, output_dir=None):
    """One selected current build/event/feedback/closure operation, no scheduler.

    Called by the research coordinator between ordinary attempts. Model repair
    uses the existing campaign executor; native plan/run/review remain separate
    ordinary actions and successful outputs return to the original assignment.
    """
    from . import agentrivet_construction as construction
    selection=follow._json(selection_pin,base_dir)
    action=selection['action'];arguments=selection['arguments']
    cycle.ce.keys(selection,{'action','arguments'})
    request_pin=arguments['request'];_,request=construction._load(request_pin,base_dir)
    if str(cycle._ordinary(root))!=request['campaign']:raise ValueError('routine step belongs to another campaign')
    if action=='generate':
        cycle.ce.keys(arguments,{'request'})
        if host is None or output_dir is None:raise ValueError('configured Host and fresh handoff destination required for generation')
        result=_routine_generation(root,None,None,request_pin,base_dir,host,_destination(root,output_dir))
    elif action=='repair':
        cycle.ce.keys(arguments,{'request','generation','feedback'})
        if host is None:raise ValueError('same explicitly configured Host required for a feedback triplet')
        result=construction.repair(request_pin,arguments['generation'],arguments['feedback'],base_dir=base_dir,host=host)
    elif action=='prepare-build':
        cycle.ce.keys(arguments,{'request','generation','source_rundir','reviewed_capsule','closure','runtime','probe','workload'})
        if output_dir is None:raise ValueError('fresh observed build preparation destination required')
        result=construction.prepare_build(request_pin,arguments['generation'],arguments['source_rundir'],arguments['reviewed_capsule'],arguments['closure'],arguments['runtime'],arguments['workload'],probe=arguments['probe'],base_dir=base_dir,output_dir=output_dir)
    elif action=='prepare-events':
        cycle.ce.keys(arguments,{'request','generation','build_rundir','event_task','histogram_mapping','workload'})
        if output_dir is None:raise ValueError('fresh complete event preparation destination required')
        result=construction.prepare_events(request_pin,arguments['generation'],arguments['build_rundir'],arguments['event_task'],arguments['histogram_mapping'],arguments['workload'],base_dir=base_dir,output_dir=output_dir)
    elif action=='close':
        cycle.ce.keys(arguments,{'request','generation','completion'})
        result=construction.close(request_pin,arguments['generation'],arguments['completion'],base_dir=base_dir)
    else:raise ValueError('unknown routine operation; no implicit native/model dispatch')
    follow._bytes(selection_pin,base_dir);return result


def recovery_context(root, identity, output_dir):
    """Consume actual criticism/failed outcomes through the existing reader.

    The same cycle retains old measurements, uncertainty, negative outcomes,
    whole-task obligations and expenditure. The caller supplies the next typed
    blueprint; this function neither invents it nor retries the old experiment.
    """
    return blueprint.prepare_context(root, _destination(root, output_dir), parent=identity)


def backend_spec(root, bundle_pin, backend_request_pin, source_binding_pin, *, base_dir, graph_id, max_wall_seconds):
    """Retired: refuses, because the external cosmology backend route was dropped (see cosmology_backend).

    This builds only the existing source-bound preparation tool. The ordinary
    cosmology-run action still requires a caller-qualified loaded binding and
    explicit nested resource admission; this command never loads or invokes it.
    """
    from . import cosmology_backend
    cosmology_backend.refuse()
    bundle = _current(bundle_pin, base_dir)
    if bundle['cycle_root'] != str(cycle._ordinary(root)):
        raise ValueError('backend handoff belongs to another parent research cycle')
    request = follow._json(backend_request_pin, base_dir)
    if request['task'] != bundle['task']:
        raise ValueError('original scientific task must remain literal at backend handoff')
    source_binding = follow._json(source_binding_pin, base_dir)
    if source_binding != request['source_binding']:
        raise ValueError('literal declared upstream source binding required')
    binding_path = follow._bytes(source_binding_pin, base_dir)[0]
    prepared = cosmology_backend.prepare(request, source_base=binding_path.parent)
    pins = [*input_pins(bundle_pin, base_dir), backend_request_pin, source_binding_pin]
    pins += [cycle._pin(row['path']) for row in prepared['source_inspection']['source_pins']]
    pins = _unique(pins, base_dir)
    rows = [{'id': 'backend-' + str(i), **_pin2(pin)} for i, pin in enumerate(pins)]
    ids = {row['path']: row['id'] for row in rows}
    return _tool_spec(graph_id, 'cosmology-prepare', rows,
        {'request_input': ids[str(cycle._ordinary(backend_request_pin['path']))],
         'source_binding_input': ids[source_binding_pin['path']]}, max_wall_seconds, node_id='prepare-backend')


def prepare_data_acquisition(specification_pin, authority_pin, context_request_pin, *,
                             base_dir, output_dir, rundir, quantity_bindings):
    """Default new ROOT acquisition: source roles -> context -> ordinary plan.

    Full original spec/policy/budget and requested quantities are retained. This
    creates an unapproved plan through science.plan; it never signs or runs it.
    Missing files produce a concrete prepared context/spec with a plan blocker.
    Legacy directly authored ROOT tasks remain inspectable and executable.
    """
    from ravel.physics import root_stream
    from . import data_read_outcomes, science
    spec_path,_=follow._bytes(specification_pin,base_dir)
    spec=follow._json(specification_pin,base_dir)
    if spec.get('mode')!='root-stream': raise ValueError('original ROOT acquisition specification required')
    root_stream.validate_scope(spec)
    original=follow._json(context_request_pin,base_dir)
    context.compile_context(original,base_dir)
    if (type(quantity_bindings) is not dict or set(quantity_bindings)!={q['id'] for q in original['requested_quantities']}):
        raise ValueError('complete original requested quantity binding required')
    destination=Path(output_dir).absolute()
    if destination.exists() or any(p.is_symlink() for p in (destination,*destination.parents)):
        raise ValueError('fresh ordinary acquisition preparation directory required')
    destination.mkdir(parents=False)
    prepared=data_read_outcomes.prepare(spec['task'],authority_pin,spec_path.parent,destination/'reader')
    request=deepcopy(original)
    for q in request['requested_quantities']:
        source_id=quantity_bindings[q['id']]
        if source_id not in prepared['read_requirements']:
            raise ValueError('original source quantity absent from acquisition')
        if 'read_requirement' in q: raise ValueError('original already bound read contract cannot be replaced')
        q['read_requirement']=deepcopy(prepared['read_requirements'][source_id])
    compiled=context.compile_context(request,base_dir)
    request_pin=_write(destination/'context-request.json',request)
    context_pin=_write(destination/'context.json',compiled)
    derivative=deepcopy(spec);derivative['task']=follow._json(prepared['task'],base_dir)
    derivative_pin=_write(destination/'specification.json',derivative)
    # The ordinary planner uses its spec document base. Every original input must
    # resolve identically in that base; no heuristic rebasing of review/goal pins.
    plan_blocker=None;plan=None
    if prepared['acquisitions_available']:
        original_inputs={str(p) for p in science.task_inputs(derivative,spec_path.parent)}
        relocated_inputs={str(p) for p in science.task_inputs(derivative,destination)}
        if original_inputs!=relocated_inputs:
            raise ValueError('relocated ordinary spec changes original scientific input paths; supply explicit absolute source pins')
        plan=science.plan(rundir,derivative_pin['path'])
    else:plan_blocker='acquisition_missing: original source files remain required before ordinary plan/run'
    follow._bytes(specification_pin,base_dir);follow._bytes(context_request_pin,base_dir)
    data_read_outcomes.requirement_pins(next(iter(prepared['read_requirements'].values())),base_dir)
    return {'kind':'prepared_data_acquisition','reader':prepared,'specification':derivative_pin,
        'original_specification':specification_pin,'original_context_request':context_request_pin,
        'context_request':request_pin,'scientific_context':context_pin,'quantity_bindings':deepcopy(quantity_bindings),
        'plan':plan,'plan_blocker':plan_blocker,'execution_authorized':False,'scientific_acceptance':False}


def data_result_context(context_pin, result_pin, *, base_dir, artifact_id, attempt_id,
                        question, next_experiment):
    """Feed real complete/partial/failed read diagnostics into original goals.

    The context checker authenticates the actual admitted ROOT reader and its
    full machine-only population. A failure cannot be replaced with observations.
    Diagnostic use is explicit in a separate original requirement; no main journal
    or ordinary execution ledger is mutated by this returned context.
    """
    compiled=follow._json(context_pin,base_dir)
    requirements=[q for q in compiled['requested_quantities'] if q['artifact']==artifact_id]
    if not requirements or any('read_requirement' not in q for q in requirements):
        raise ValueError('original source-bound acquisition requirements required')
    raw=follow._json(result_pin,base_dir)
    if raw.get('kind')!='root-stream-result': raise ValueError('actual ROOT reader result required')
    returned=context.apply_step(compiled,{'id':attempt_id,'outputs':{artifact_id:_pin2(result_pin)},
        'code_status':'success' if raw['status']=='passed' else 'failure','actor_complete':False,
        'question':question,'next_experiment':next_experiment},base_dir)
    follow._bytes(context_pin,base_dir);follow._bytes(result_pin,base_dir)
    return {'kind':'unaccepted_data_quantity_context','result':deepcopy(result_pin),
        'read_summary':deepcopy(raw['read_summary']),'scientific_context':returned,
        'scientific_acceptance':False,'parent_task_accepted':False}


def data_operations():
    """Invocable ordinary acquisition/reader/context paths for the coordinator."""
    return {'new_acquisition':{'entrypoint':'research_tools.prepare_data_acquisition',
        'cli_operation':'data-prepare','mode':'root-stream',
        'requires':['original ordinary spec','pinned source-role authority','original quantity context',
                    'complete quantity bindings','fresh preparation and run destinations'],
        'emits':['read contract','original unresolved quantities','existing unapproved ordinary plan or missing-acquisition blocker']},
        'reader':{'entrypoint':'root_stream.run','requires':'existing ordinary approve/run authority; same original branch/unit/normalization laws'},
        'result_context':{'entrypoint':'research_tools.data_result_context','cli_operation':'data-result-context',
            'requires':'actual admitted reader result plus original source-bound quantity context'},
        'new_scheduler':False,'execution_authorized':False,'physics_validated':False}


def backend_result_context(bundle_pin, raw_result_pin, *, base_dir, outputs, attempt_id,
                           question, next_experiment):
    """Keep actual returned artifact checks separate from backend success prose.

    The raw return is a supplied retained artifact, never a fabricated
    execution receipt. The result can be a failure/procedure context for a fresh
    ordinary blueprint. It confers no execution, role vote or parent acceptance
    and never overwrites the main research journal or revives an old attempt.
    """
    from . import cosmology_backend
    cosmology_backend.refuse()
    bundle = _current(bundle_pin, base_dir)
    result = cosmology_backend.read_results(follow._json(raw_result_pin, base_dir))
    compiled = follow._json(bundle['api_context'], base_dir)
    returned = cosmology_backend.apply_results(compiled, result, outputs=outputs,
        attempt_id=attempt_id, question=question, next_experiment=next_experiment, base_dir=Path(base_dir))
    _current(bundle_pin, base_dir)
    follow._bytes(raw_result_pin, base_dir)
    return {'kind': 'unaccepted_backend_quantity_context', 'raw_return': raw_result_pin,
        'bundle': bundle_pin, 'backend_report': result, 'scientific_context': returned,
        'execution_receipt_inferred': False, 'scientific_acceptance': False, 'parent_task_accepted': False}



def backend_recovery(root, bundle_pin, raw_result_pin, blueprint_pin, output_dir, *,
                     base_dir, outputs, attempt_id, question, next_experiment):
    """Feed real retained backend artifacts into a fresh ordinary design.

    Source assertions and missing quantities become explicit designer context,
    not an accepted scientific observation or an execution receipt. The caller
    supplies the fresh typed intervention; existing portfolio admission decides
    whether it can be planned. All original quantities and parent obligations
    remain active, with no retry or budget reset.
    """
    bundle = _current(bundle_pin, base_dir)
    if bundle['cycle_root'] != str(cycle._ordinary(root)):
        raise ValueError('backend feedback belongs to another research cycle')
    source_pins = [raw_result_pin]
    for declared in outputs.values():
        raw_path = Path(declared['path'])
        raw_path = raw_path if raw_path.is_absolute() else Path(base_dir) / raw_path
        actual = cycle._pin(raw_path)
        if actual['sha256'] != declared['sha256']:
            raise ValueError('retained backend output changed')
        source_pins.append(actual)
    snapshots = [blueprint._snapshot(pin, base_dir) for pin in source_pins]
    out = _destination(root, output_dir)
    feedback = backend_result_context(bundle_pin, raw_result_pin, base_dir=base_dir, outputs=outputs,
        attempt_id=attempt_id, question=question, next_experiment=next_experiment)
    feedback_pin = _write(out / 'backend-feedback.json', feedback)
    documents = [{'id': 'retained-backend-' + str(i), 'pin': _pin2(pin), 'language': 'json',
        'role': 'example', 'version': 'Literal retained backend artifact; no execution or acceptance inferred',
        'dependencies': []} for i, pin in enumerate(source_pins)]
    documents.append({'id': 'backend-feedback', 'pin': _pin2(feedback_pin), 'language': 'json',
        'role': 'example', 'version': 'Actual quantity checker applied to supplied retained results; unaccepted',
        'dependencies': [row['id'] for row in documents]})
    fresh = prepare(root, blueprint_pin, out / 'context', api_documents=documents,
        queries=[{'id': 'backend-quantity-feedback', 'symbol': 'quantity_completion', 'mode': 'occurrence',
            'documents': ['backend-feedback'], 'required': True}])
    blueprint._fresh_snapshots(snapshots, base_dir)
    _current(bundle_pin, base_dir)
    return {'kind': 'unaccepted_backend_recovery_handoff', 'bundle': fresh, 'feedback': feedback_pin,
        'execution_receipt_inferred': False, 'execution_authorized': False,
        'scientific_acceptance': False, 'parent_task_accepted': False}


def backend_execution_spec(root, bundle_pin, backend_request_pin, source_binding_pin, runtime_pin, *,
                           base_dir, graph_id, overhead_seconds):
    """Prepare the existing bounded callable route, with all nested ceilings.

    No loaded runtime is discovered here. Actual dispatch requires an explicit
    Host RuntimeBinding whose fresh identity equals runtime_pin, the machine
    lease and each ordinary tool's approval. Graph reservations include all
    nested calls/tokens plus the outer tool call, never just one facade call.
    """
    from . import cosmology_backend
    cosmology_backend.refuse()
    from . import cosmology_runtime
    if type(overhead_seconds) is not int or not 1 <= overhead_seconds <= 3600:
        raise ValueError('explicit positive source/admission/readback overhead required')
    identity = follow._json(runtime_pin, base_dir)
    if (identity.get('kind') != 'explicit-derivative-runtime'
            or identity.get('runtime_module_sha256') != cycle._pin(cosmology_runtime.__file__)['sha256']):
        raise ValueError('exact current declared runtime binding source required')
    cosmology_runtime.validate_limits(identity['limits'])
    limits = identity['limits']
    spec = backend_spec(root, bundle_pin, backend_request_pin, source_binding_pin, base_dir=base_dir,
        graph_id=graph_id, max_wall_seconds=limits['wall_seconds'] + overhead_seconds)
    refs = ([identity['source_inventory_pin']] if identity['source_inventory_pin'] is not None
            else identity['source_pins']) + identity['known_execution_sources']
    supplied = [runtime_pin] + [cycle._pin(row['path']) for row in refs]
    for declared, actual in zip(refs, supplied[1:]):
        if declared['sha256'] != actual['sha256']:
            raise ValueError('declared runtime execution source changed')
    old = [{**row, 'size': Path(row['path']).stat().st_size} for row in spec['nodes'][0]['inputs']]
    old = [{k: row[k] for k in ('path', 'sha256', 'size')} for row in old]
    pins = _unique([*old, *supplied], base_dir)
    rows = [{'id': 'backend-' + str(i), **_pin2(pin)} for i, pin in enumerate(pins)]
    ids = {row['path']: row['id'] for row in rows}
    spec['nodes'][0].update(id='execute-backend', role='executor', action='research-backend', inputs=rows,
        parameters={'bundle_input': ids[str(cycle._ordinary(bundle_pin['path']))],
            'request_input': ids[str(cycle._ordinary(backend_request_pin['path']))],
            'source_binding_input': ids[str(cycle._ordinary(source_binding_pin['path']))],
            'runtime_input': ids[str(cycle._ordinary(runtime_pin['path']))], 'overhead_seconds': overhead_seconds})
    spec['budget']['max_calls'] = limits['calls'] + 1
    spec['budget']['max_output_tokens'] = limits['output_tokens']
    agent_graph.validate(spec)
    return spec


def host_backend(parameters, pins, control, presented_pins, binding):
    """Authenticate one explicitly supplied loaded binding before delegation."""
    from . import cosmology_backend
    cosmology_backend.refuse()
    cycle.ce.keys(parameters, {'bundle_input', 'request_input', 'source_binding_input', 'runtime_input', 'overhead_seconds'})
    if binding is None:
        raise ValueError('explicit caller-qualified loaded runtime required; no discovery or installation')
    refs = {}
    for key in ('bundle_input', 'request_input', 'source_binding_input', 'runtime_input'):
        if parameters[key] not in pins:
            raise ValueError('explicit normal context/backend/runtime Graph inputs required')
        path, sha = pins[parameters[key]]
        refs[key] = {'path': str(path), 'sha256': sha, 'size': path.stat().st_size}
    base = Path(refs['bundle_input']['path']).parent
    bundle = _current(refs['bundle_input'], base)
    runtime = follow._json(refs['runtime_input'], base)
    if binding.identity != runtime:
        raise ValueError('actual loaded runtime differs from the admitted identity/limits')
    actual, _ = agent_graph._load(control.root)
    expected = backend_execution_spec(bundle['cycle_root'], refs['bundle_input'], refs['request_input'],
        refs['source_binding_input'], refs['runtime_input'], base_dir=base, graph_id=actual['graph_id'],
        overhead_seconds=parameters['overhead_seconds'])
    _, state = cycle._load(bundle['cycle_root'])
    if 'goal_binding' in state['contract']:
        expected['goal_binding'] = deepcopy(state['contract']['goal_binding'])
    if actual != expected or str(cycle._ordinary(control.root)) not in {row['root'] for row in state['graphs']}:
        # During the first dispatch the journal records its reservation before
        # observation, so the exact reservation is the authoritative genealogy.
        reservation = next((row for row in state['resource_ledger'] if row['id'] == 'graph:' + str(cycle._ordinary(control.root))), None)
        if actual != expected or reservation is None or reservation['basis']['specification_sha256'] != cycle.ce.digest(actual):
            raise ValueError('exact cumulatively reserved full nested workflow Graph required')
    snapshots = [blueprint._snapshot({'path': row['path'], 'sha256': row['sha256'],
        'size': Path(row['path']).stat().st_size}, base) for row in presented_pins]
    control.check_cancelled()
    request = follow._json(refs['request_input'], base)
    value = binding.run(request, source_base=Path(refs['source_binding_input']['path']).parent,
        control=control, graph_input_pins=presented_pins)
    blueprint._fresh_snapshots(snapshots, base)
    if binding.identity != runtime:
        raise ValueError('runtime identity or nested limits changed during the workflow')
    _current(refs['bundle_input'], base)
    return value


# ---- governed literature query expansion and evidence scoring (explicit campaign operations)

# Role-dispatcher transports that carry one structured model call through the ordinary Host.
LITERATURE_ADAPTERS = {'http-responses': 'responses', 'http-anthropic': 'anthropic', 'http-gemini': 'gemini',
                       'http-chat': 'chat_completions', 'external-relay': 'external'}
EXPANSION_KIND = 'literature-query-expansion-operation'
SCORING_KIND = 'literature-evidence-scoring-operation'


def _literature_card(role, roles):
    from . import role_registry
    if roles is not None:
        entry = (roles.get('roles') or {}).get(role) if isinstance(roles, dict) else None
        return entry.get('card') if isinstance(entry, dict) else None
    try:
        return role_registry.load(role)
    except (KeyError, ValueError, OSError):
        return None


def _literature_dispatch(role, roles, preferences, probes, executables=None):
    """The role dispatcher's selection for a literature role card, or the reason it refuses.

    In a controller scope the existing governed host runs these model nodes as seats. Selection
    uses that scope's frozen preferences and protected qualifications; the seat repeats admission
    at its enforcing action. Outside it, only the ordinary Host's one-shot adapters are carried.
    """
    from . import research_controller, role_registry, transport_registry
    card = _literature_card(role, roles)
    if not isinstance(card, dict) or not isinstance(card.get('model'), dict) or not card.get('family'):
        return None, {'reason': 'role_card_unavailable'}
    current = research_controller.active()
    if current is not None:
        from ravel.controller.step import seats
        from ravel.controller.step.services import StepHold
        # A caller's synthetic card or probe may never change a governed seat's installed duties.
        if card != role_registry.load(role):
            return None, {'reason': 'role_card_changed'}
        store, context = current
        try:
            prefs, _, _ = seats.preferences(context, card)
            selection = seats.select(card, prefs, store=store)
        except StepHold as exc:
            missing = list((exc.evidence or {}).get('missing') or [])
            tier = any(str(m).startswith(('model:', 'tier:')) for m in missing)
            return None, {'reason': 'model_tier_unavailable' if tier else exc.reason, 'missing': missing}
        return {**deepcopy(selection), 'adapter': 'model', 'tier': selection.get('tier') or card['model']['tier']}, None
    try:
        selection = transport_registry.select(card, preferences, probes=probes, executables=executables)
    except transport_registry.TransportRefusal as exc:
        missing = list(getattr(exc, 'missing', []) or [])
        tier = any(str(m).startswith(('model:', 'tier:')) for m in missing)
        return None, {'reason': 'model_tier_unavailable' if tier else 'transport_unavailable', 'missing': missing}
    adapter = LITERATURE_ADAPTERS.get(selection['transport_id'])
    if adapter is None:
        return None, {'reason': 'transport_unsupported', 'missing': [selection['transport_id']]}
    return {**deepcopy(selection), 'adapter': adapter, 'tier': card['model']['tier']}, None


def _literature_graph(root, graph_root, spec, host):
    """Run one literature Graph under the campaign reservation; return the refusal reason or None."""
    from . import graph_substrate
    try:
        # The shared role-dispatch boundary: the campaign reserves, charges and records the Graph.
        graph_substrate.execute_role_graph(root, graph_root, spec, host, prepared=False, workers=1)
    except cycle.OperationalBoundaryError as exc:
        return {'reason': 'allowance_exhausted', 'error': str(exc)[:512]}
    except (ValueError, agent_graph.GraphError) as exc:
        exhausted = 'exhausted' in str(exc) or 'ceiling' in str(exc)
        return {'reason': 'allowance_exhausted' if exhausted else 'graph_failed',
                'error': type(exc).__name__ + ': ' + str(exc)[:512]}
    return None


def _operation_record(out, record):
    path = out / 'operation.json'
    _write(path, record)
    return record


def expand_literature_query(root, query, output_dir, host, *, preferences, max_wall_seconds=300,
                            max_output_tokens=1024, limits=None, known_tokens=None, vocabulary=None, roles=None,
                            probes=None, executables=None):
    """Governed query expansion: the deterministic expansion, plus at most one dispatched, charged choice.

    The deterministic expansion is always returned and never depends on a model.
    The registered expander card is dispatched through the role dispatcher; its
    one Graph call is reserved and charged by the campaign. A missing card, an
    unserved model tier, an exhausted allowance or a refused reply is recorded
    with its reason, and only the deterministic terms stand.
    """
    from . import literature_query as q
    out = _destination(root, output_dir)
    out.mkdir()
    deterministic = q.expand(query, limits=limits, vocabulary=vocabulary, known_tokens=known_tokens)
    record = {'schema_version': 1, 'kind': EXPANSION_KIND, 'query': query, 'role': q.ROLE, 'status': 'refused',
              'reason': None, 'dispatch': None, 'request': None, 'graph': None, 'error': None,
              'deterministic': deterministic, 'expansion': deterministic, 'search_hints_only': True,
              'physics_verified': False}
    try:
        document = q.request_document(query, limits=limits, vocabulary=vocabulary, roles=roles)
    except ValueError as exc:
        record['reason'] = 'role_card_unavailable' if 'role_card_unavailable' in str(exc) else 'invalid_request'
        return _operation_record(out, record)
    selection, refusal = _literature_dispatch(q.ROLE, roles, preferences, probes, executables)
    if refusal:
        record.update(refusal)
        return _operation_record(out, record)
    pin = q.write_request(out / 'request.json', document, vocabulary=vocabulary, roles=roles)
    spec = q.graph_spec(pin, graph_id='literature-query-expansion-' + pin['sha256'][:16], model=selection['model'],
                        reasoning_effort=selection['effort'] or 'low', adapter=selection['adapter'],
                        max_output_tokens=max_output_tokens, max_wall_seconds=max_wall_seconds,
                        vocabulary=vocabulary, roles=roles)
    graph_root = out / 'graph'
    record.update(dispatch=selection, request=pin, graph=str(graph_root))
    failed = _literature_graph(root, graph_root, spec, host)
    if failed:
        record.update(failed)
        return _operation_record(out, record)
    expansion = q.expand(query, governed={'request': pin, 'graph_root': str(graph_root)}, limits=limits,
                         vocabulary=vocabulary, known_tokens=known_tokens, roles=roles, campaign_root=root)
    admitted = expansion['model']['status'] == 'admitted'
    record.update(expansion=expansion, status='admitted' if admitted else 'refused',
                  reason=None if admitted else expansion['model'].get('reason'))
    return _operation_record(out, record)


def served_envelope(rundir, serving_id, *, node_id, attempt):
    """The search envelope serving delivered to one worker attempt, from supervisor custody.

    The located bytes must equal their recorded digest and output pin; the
    measured time comes from the same served record. Anything else is stale.
    """
    from . import broker as core, literature_serving
    admitted, served, withdrawn = None, None, False
    for row in core.ledger(rundir, literature_serving.LEDGER):
        value = row['record']
        if value.get('action') != literature_serving.ACTION:
            continue
        if 'serving_id' not in value and value['event'] == 'admitted' and 'serving:%d' % row['n'] == serving_id:
            admitted = value
        elif value.get('serving_id') == serving_id:
            if value['event'] == 'served':
                served = value
            elif value['event'] == 'denied':
                withdrawn = True
    if admitted is None or served is None or withdrawn:
        raise ValueError('no delivered literature result has this serving identity')
    binding = served['binding']
    if (binding['node_id'], binding['attempt']) != (node_id, attempt) or admitted['request']['operation'] != 'search':
        raise ValueError('the served search belongs to another worker attempt or operation')
    raw = None
    for row in core.ledger(rundir, 'broker'):
        value = row['record']
        receipt = core.verify_broker_receipt(rundir, {'path': value['path'], 'sha256': value['sha256']},
                                             verify_outputs=False)
        reply = receipt['reply']
        if (receipt['action'] == literature_serving.ACTION and reply.get('status') == 'ok'
                and literature_serving._reply_serving_id(reply) == serving_id):
            # The broker receipt and its output pin authenticate the delivered bytes.
            raw = literature_serving.load(rundir, reply)
            break
    if raw is None or hashlib.sha256(raw).hexdigest() != served['located_sha256']:
        raise ValueError('the served literature bytes are missing or changed after custody')
    envelope = json.loads(raw)
    envelope['usage'] = {**envelope['usage'], 'elapsed_seconds': served['usage']['elapsed_seconds']}
    return deepcopy(admitted['request']), envelope


def score_literature_evidence(root, rundir, serving_id, question, output_dir, host, *, node_id, attempt,
                              preferences, limits=None, max_wall_seconds=600, max_output_tokens=None, roles=None,
                              probes=None, executables=None):
    """Batched evidence scoring of one served search, dispatched under the scorer card and charged.

    The envelope comes from serving custody (``served_envelope``), never from the
    caller. Every original passage is returned beside its assessment; a refused
    dispatch, an exhausted allowance or a failed batch leaves its candidates with
    the reason and no score. Scores and summaries are reading aids, never evidence.
    """
    from . import literature_evidence_scoring as s
    out = _destination(root, output_dir)
    out.mkdir()
    record = {'schema_version': 1, 'kind': SCORING_KIND, 'question': question, 'role': s.ROLE,
              'serving_id': serving_id, 'status': 'refused', 'reason': None, 'dispatch': None, 'request': None,
              'graph': None, 'error': None, 'scoring': None, 'summaries_are_evidence': False,
              'physics_verified': False}
    try:
        search_request, envelope = served_envelope(rundir, serving_id, node_id=node_id, attempt=attempt)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        record.update(reason='stale_envelope', error=str(exc)[:512])
        return _operation_record(out, record)
    try:
        document = s.request_document(question, search_request, envelope, limits=limits, roles=roles)
    except ValueError as exc:
        record['reason'] = 'role_card_unavailable' if 'role_card_unavailable' in str(exc) else 'invalid_request'
        return _operation_record(out, record)
    pin = s.write_request(out / 'request.json', document, roles=roles)
    record['request'] = pin
    graph_root = None
    if document['batches']:
        selection, refusal = _literature_dispatch(s.ROLE, roles, preferences, probes, executables)
        if refusal:
            record.update(refusal)
        else:
            spec = s.graph_spec(pin, graph_id='literature-evidence-scoring-' + pin['sha256'][:16],
                                model=selection['model'], reasoning_effort=selection['effort'] or 'low',
                                adapter=selection['adapter'], max_output_tokens=max_output_tokens,
                                max_wall_seconds=max_wall_seconds, roles=roles)
            candidate = out / 'graph'
            record.update(dispatch=selection, graph=str(candidate))
            failed = _literature_graph(root, candidate, spec, host)
            if failed:
                record.update(failed)
            else:
                graph_root = candidate
    scoring = s.assemble(pin, graph_root, roles=roles, campaign_root=root)
    record['scoring'] = s.write_record(out / 'record.json', scoring)
    if record['reason'] is None:
        complete = scoring['status'] in ('complete', 'nothing_to_score')
        record.update(status='scored' if complete else scoring['status'],
                      reason=None if complete else 'batch_failed')
    record['outcome'] = {'status': scoring['status'], 'scored': sum(e['assessment']['status'] == 'scored'
                                                                    for e in scoring['evidence']),
                         'candidates': len(scoring['evidence'])}
    return _operation_record(out, record)


CRAWL_KIND = 'literature-discovery-crawl-operation'


def _crawl_record_path(out):
    # Beside the agent's ledger directory, which owns its own population.
    return out.parent / (out.name + '.operation.json')


def _crawl_record(out, record):
    from . import state_io
    state_io.atomic_json(_crawl_record_path(out), record)
    return record


def crawl_literature(root, scope_pin, output_dir, host, *, preferences=None, probes=None, max_output_tokens=2048,
                     max_wall_seconds=60, max_advances=None, graph=None, roles=None, executables=None):
    """Discovery as the bounded selector loop: start, advance, admitted selections, report and consume.

    A fresh ``output_dir`` starts the ledger; an existing one resumes it, after
    the ledger, scope and products are recomputed (a tampered or stale crawl is
    refused). With ``preferences`` the registered selector card is dispatched
    through the role dispatcher; each selector Graph runs through the shared
    role-dispatch boundary, so the campaign reserves and charges it, and a refused
    call is declined, which stops selection. Without ``preferences`` the crawl is
    deterministic. ``max_advances`` pauses the loop (resume continues it). A
    budget exhaustion halts with a qualified, dated lower-bound report. The
    single-query ``discover_literature`` call stays separate and cannot satisfy
    this receipt (``admit_crawl``).
    """
    from . import literature_discovery_agent as agent
    out = cycle._ordinary(Path(output_dir))
    record = {'schema_version': 1, 'kind': CRAWL_KIND, 'output': str(out), 'role': agent.ROLE, 'status': 'refused',
              'reason': None, 'dispatch': None, 'advances': 0, 'report': None, 'counts': None, 'error': None,
              'claims': deepcopy(agent.CLAIMS)}
    if (max_advances is not None and (type(max_advances) is not int or max_advances < 1)):
        raise ValueError('max_advances must be a positive integer or None')
    resumed = (out / 'ledger').is_dir()
    if resumed:
        try:
            current = agent.status(root, out, roles=roles)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            record.update(reason='stale_crawl', error=str(exc)[:512])
            return record
        record['resumed_from'] = current.get('status')
    else:
        selector = None
        if preferences is not None:
            selection, refusal = _literature_dispatch(agent.ROLE, roles, preferences, probes, executables)
            if refusal:
                record.update(refusal)
                return record
            record['dispatch'] = selection
            selector = {'model': selection['model'], 'reasoning_effort': selection['effort'] or 'low',
                        'adapter': selection['adapter'], 'max_output_tokens': max_output_tokens,
                        'max_wall_seconds': max_wall_seconds}
        agent.start(root, scope_pin, out, selector=selector, graph=graph, roles=roles)
    record['resumed'] = resumed

    def step_once(**kwargs):
        record['advances'] += 1
        return agent.advance(root, out, host, roles=roles, **kwargs)
    step = step_once()
    while step['status'] == 'select':
        if max_advances is not None and record['advances'] >= max_advances:
            record.update(status='paused', pending=step['graph_root'])
            return _crawl_record(out, record)
        graph_root = Path(step['graph_root'])
        if not graph_root.exists():
            failed = _literature_graph(root, graph_root, step['graph_spec'], host)
            if failed and not graph_root.is_dir():
                step = step_once(decline=('selector call refused: ' + failed['reason'])[:500])
                continue
        step = step_once(selection=str(graph_root))
    report = agent.consume(root, out, roles=roles)
    record.update(status=step['status'], reason='halted: ' + str(report.get('halt_reason'))[:400]
                  if step['status'] == 'halted' else None, report=deepcopy(step['report']),
                  counts=deepcopy(report.get('counts')), usage=deepcopy(report.get('usage')))
    return _crawl_record(out, record)


def admit_crawl(root, output_dir, *, roles=None):
    """The selector-loop receipt: the recomputed report of an ended crawl and its operation record.

    Only a hash-chained crawl ledger that ended and whose report recomputes
    exactly satisfies it; a single discovery query's product does not.
    """
    from . import literature_discovery_agent as agent
    out = cycle._ordinary(Path(output_dir))
    if not (out / 'ledger').is_dir():
        raise ValueError('no selector-loop ledger: a single discovery query is not a crawl')
    report = agent.consume(root, out, roles=roles)
    path = _crawl_record_path(out)
    record = json.loads(path.read_text()) if path.is_file() else None
    if (not isinstance(record, dict) or record.get('kind') != CRAWL_KIND or record.get('status') not in
            ('complete', 'halted') or record.get('output') != str(out)
            or {k: (record.get('report') or {}).get(k) for k in ('sha256', 'size')}
            != {k: cycle._pin(out / 'report.json')[k] for k in ('sha256', 'size')}):
        raise ValueError('the crawl operation record does not match its recomputed report')
    return {'record': record, 'report': report}


def literature_operations():
    """Explicit controller operations above literature search; search itself never calls a model."""
    return {'literature-query-expansion': {'entrypoint': 'research_tools.expand_literature_query',
                                           'cli_operation': 'literature-expand', 'role': 'literature-query-expander'},
            'literature-evidence-scoring': {'entrypoint': 'research_tools.score_literature_evidence',
                                            'cli_operation': 'literature-score', 'role': 'literature-evidence-scorer'},
            'literature-discovery-crawl': {'entrypoint': 'research_tools.crawl_literature',
                                           'cli_operation': 'literature-crawl', 'role': 'literature-discovery-selector',
                                           'receipt': 'research_tools.admit_crawl'},
            'deterministic_expansion': {'entrypoint': 'literature_query.expand', 'governed': None,
                                        'model_calls': 0},
            'new_scheduler': False, 'execution_authorized': False, 'physics_validated': False}


def _literature_cli(operation, value):
    from .agent_host import AgentHost
    function = {'literature-expand': expand_literature_query, 'literature-score': score_literature_evidence,
                'literature-crawl': crawl_literature}[operation]
    return function(host=AgentHost(), **value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'model-proposals', 'choice-spec', 'materialization-spec', 'admission-spec', 'plan', 'plan-workflow', 'recovery', 'data-prepare', 'data-result-context', 'backend-spec', 'backend-execution-spec', 'backend-result-context', 'backend-recovery',
        'literature-expand', 'literature-score', 'literature-crawl'))
    parser.add_argument('--request', required=True, help='bounded exact JSON arguments; pins include path/sha256/size')
    args = parser.parse_args(argv)
    value = cycle._cli_document(args.request)
    operations = {'prepare': prepare, 'model-proposals': prepare_model_proposals, 'choice-spec': choice_spec, 'materialization-spec': materialization_spec,
        'admission-spec': admission_spec, 'plan': plan, 'plan-workflow': plan_workflow, 'recovery': recovery_context,
        'data-prepare':prepare_data_acquisition,'data-result-context':data_result_context,
        'backend-spec': backend_spec, 'backend-execution-spec': backend_execution_spec, 'backend-result-context': backend_result_context, 'backend-recovery': backend_recovery}
    result = (_literature_cli(args.operation, value) if args.operation.startswith('literature-')
              else operations[args.operation](**value))
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0
