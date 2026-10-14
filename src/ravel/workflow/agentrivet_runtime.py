"""Bind all four original external AgentRivet factories to one GraphLLM.

The original modules, prompts, output models and ReviewLoop remain external.
No upstream GPL prompt or function body is distributed here. This API accepts
explicitly loaded modules; it does not import/install SDKs, find credentials,
fetch a paper, call a provider, compile a routine or authorize an event run.
"""
import ast
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from types import CodeType, ModuleType
import sys
import threading

from ravel.physics import agentrivet_candidate as candidate
from .agentrivet_provider import GraphLLM
from . import agent_graph, agentrivet_pins, state_io

ROLES = {
    "analyst": ("analyst_agent.py", "AnalystAgent", "ANALYST_PROMPT", "AnalysisModel"),
    "coder": ("coder_agent.py", "CoderAgent", "CODER_PROMPT", None),
    "code_reviewer": ("code_reviewer_agent.py", "CodeReviewerAgent", "CODE_REVIEWER_PROMPT", "CodeReviewModel"),
    "physics_reviewer": ("physics_reviewer_agent.py", "PhysicsReviewerAgent", "PHYSICS_REVIEWER_PROMPT", "PhysicsReviewModel"),
}
_LOCK = threading.Lock()


def _code(code, name):
    for value in code.co_consts:
        if isinstance(value, CodeType):
            if value.co_name == name: return value
    raise ValueError("required original upstream definition absent")


def _same_code(actual, expected):
    # Marshal serialization includes internal interning/reference flags. Those
    # can differ between equal loaded and freshly compiled code objects. Compare
    # every executable/source-location field and typed constant recursively.
    def signature(code):
        constants = tuple(signature(v) if isinstance(v, CodeType) else (type(v).__name__, repr(v))
                          for v in code.co_consts)
        fields = tuple(getattr(code, name) for name in (
            'co_argcount', 'co_posonlyargcount', 'co_kwonlyargcount', 'co_nlocals', 'co_stacksize',
            'co_flags', 'co_code', 'co_names', 'co_varnames', 'co_filename', 'co_name', 'co_qualname',
            'co_firstlineno', 'co_linetable', 'co_exceptiontable', 'co_freevars', 'co_cellvars'))
        return fields, constants
    return signature(actual) == signature(expected)


def _module(module, pin, filename):
    if not isinstance(module, ModuleType): raise ValueError("explicit already-loaded external module required")
    path, raw = candidate._snapshot(pin, Path.cwd())
    if path.name != filename or Path(module.__file__).absolute() != path:
        raise ValueError("module must come from its exact pinned upstream file")
    return path, raw, compile(raw, str(path), "exec", dont_inherit=True)


def inspect_binding(core, roles, *, source_pins):
    """Check original loaded factories and literal prompt bindings without calls.

    Byte/code identity is source qualification, not installed Pydantic/provider
    or interpreter ABI certification. Schema adaptation remains GraphLLM's job.
    """
    if type(roles) is not dict or set(roles) != set(ROLES):
        raise ValueError("all four actual upstream role modules required")
    if type(source_pins) is not dict or set(source_pins) != {"core", *ROLES}:
        raise ValueError("exact core plus four role source pins required")
    path, raw, compiled = _module(core, source_pins["core"], "core.py")
    for name in ("make_llm",):
        value = getattr(core, name, None)
        if not inspect.isfunction(value) or value.__globals__ is not core.__dict__ or not _same_code(value.__code__, _code(compiled, name)):
            raise ValueError("original loaded core factory differs from pinned code")
    for cls_name in ("Agent", "ReviewLoop"):
        cls = getattr(core, cls_name, None)
        original = _code(compiled, cls_name)
        for member in original.co_consts:
            if isinstance(member, CodeType):
                method = getattr(cls, member.co_name, None)
                if not inspect.isfunction(method) or not _same_code(method.__code__, member):
                    raise ValueError("original loaded Agent/ReviewLoop method differs")
    receipts = {}
    for role, (filename, factory_name, prompt_name, output_name) in ROLES.items():
        module = roles[role]
        role_path, role_raw, code = _module(module, source_pins[role], filename)
        factory = getattr(module, factory_name, None)
        if (not inspect.isfunction(factory) or factory.__globals__ is not module.__dict__
                or not _same_code(factory.__code__, _code(code, factory_name))
                or module.Agent is not core.Agent or module.make_llm is not core.make_llm):
            raise ValueError("all four original by-value factory bindings required")
        tree = ast.parse(role_raw)
        assignment = next((n for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == prompt_name for t in n.targets)), None)
        original_prompt = ast.literal_eval(assignment.value) if assignment else None
        if type(original_prompt) is not str or getattr(module, prompt_name, None) != original_prompt:
            raise ValueError("original external prompt value changed")
        model = None if output_name is None else getattr(module, output_name, None)
        if output_name is not None and (not inspect.isclass(model) or model.__module__ != module.__name__
                or not callable(getattr(model, "model_json_schema", None)) or not callable(getattr(model, "model_validate", None))):
            raise ValueError("original external output model interface required")
        receipts[role] = {"source": deepcopy(source_pins[role]), "factory": factory_name,
            "prompt_sha256": hashlib.sha256(original_prompt.encode()).hexdigest(),
            "output_model": output_name, "prompt_distributed": False}
    for pin in source_pins.values(): candidate._snapshot(pin, Path.cwd())
    # Loaded core/role bytes must come from one allowed upstream commit.
    commits = agentrivet_pins.admit_member_pins(source_pins)
    return {"kind": "agentrivet_original_factory_binding", "sources": deepcopy(source_pins), "roles": receipts,
        "upstream_role_commits": commits,
        "all_four_by_value_bindings_checked": True, "loaded_factory_code_checked": True,
        "provider_runtime_qualified": False, "pydantic_runtime_qualified": False,
        "scientific_review": False, "execution_authorized": False, "physics_validated": False}


@contextmanager
def _temporary_factories(core, roles, llm, provider, model):
    # Global factory names imported by value cannot be fixed by replacing only
    # core.make_llm. Bind every role module, restore even on SystemExit/exception.
    if not _LOCK.acquire(blocking=False): raise ValueError("upstream factory construction already active")
    old = {role: module.make_llm for role, module in roles.items()}
    observed = []
    def factory(actual_provider, actual_model):
        if (actual_provider, actual_model) != (provider, model):
            raise ValueError("original upstream factory requested another provider/model")
        observed.append((actual_provider, actual_model))
        return llm
    try:
        for module in roles.values(): module.make_llm = factory
        yield observed
    finally:
        for role, module in roles.items(): module.make_llm = old[role]
        _LOCK.release()


def instantiate(core, roles, llm, *, source_pins, provider, model, max_iterations, brief_source=None, observer=None):
    """Construct original Agents/ReviewLoop sharing one cumulative Graph provider.

    No generation is invoked. The caller later invokes the returned ORIGINAL
    ReviewLoop with explicitly acquired Memory/paper/HEPData context. Upstream
    reviewer annotations remain advisory; only ordinary RAVEL reviews qualify
    a subsequent source/build/event result.
    """
    if type(llm) is not GraphLLM: raise ValueError("one explicit bounded ordinary GraphLLM required")
    if (type(provider) is not str or not provider.strip() or type(model) is not str
            or model != llm.model or type(max_iterations) is not int or not 1 <= max_iterations <= 3):
        raise ValueError("exact declared provider/model and finite original loop required")
    receipt = inspect_binding(core, roles, source_pins=source_pins)
    declared = {(p['path'], p['sha256']) for p in llm.source_inputs}
    if any((p['path'], p['sha256']) not in declared for p in source_pins.values()):
        raise ValueError('all original factory/module bytes must be normal Graph provider source inputs')
    # Analyst + one coder/code-review/physics-review per round; cache skipping
    # cannot justify a smaller prospective worst-case call reservation.
    required = 1 + 3 * max_iterations
    if llm.calls < required:
        raise ValueError("one cumulative provider must reserve every original loop role call")
    agents = {}
    with agentrivet_pins.no_subprocess("original role construction"), \
            _temporary_factories(core, roles, llm, provider, model) as observed:
        for role, (_, factory_name, _, _) in ROLES.items():
            agents[role] = getattr(roles[role], factory_name)(provider, model)
        if len(observed) != 4: raise ValueError("exactly one provider binding per original role required")
    # Source/code/prompt values are checked again after construction, after
    # by-value names have been restored. Original valid() uses source-only pins.
    if inspect_binding(core, roles, source_pins=source_pins) != receipt:
        raise ValueError("upstream source bindings changed during construction")
    with agentrivet_pins.no_subprocess("original ReviewLoop construction"):
        loop = core.ReviewLoop(agents["analyst"], agents["coder"], agents["code_reviewer"],
            agents["physics_reviewer"], max_iterations=max_iterations)
    for role, agent in agents.items():
        _, _, prompt, output = ROLES[role]
        if (agent.__class__ is not core.Agent or agent.llm is not llm
                or agent.system_prompt != getattr(roles[role], prompt)
                or agent.output_model is not (None if output is None else getattr(roles[role], output))):
            raise ValueError("original Agent constructor/prompt/model identity changed")
    if getattr(llm, 'campaign_root', None) is not None:
        # Name every call's role by its exact original system prompt.
        llm.bind_construction({role: getattr(roles[role], ROLES[role][2]) for role in ROLES},
                              brief_source=brief_source, observer=observer)
    receipt.update({"max_iterations": max_iterations, "required_call_ceiling": required,
        "provider_call_ceiling": llm.calls, "one_cumulative_graph_provider": True,
        "original_factory_names_restored": True, "provider_calls_made": 0,
        "upstream_stopping_rules_preserved": True})
    return loop, receipt


def _document(path):
    path = Path(path).absolute()
    pin = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return pin, candidate._json(candidate._snapshot(pin, Path.cwd())[1])


def generation_outputs(llm):
    """Read all genuine completed Graph calls in original generator-stage order.

    A fully fresh Analyst/Coder/reviewer history is supported. Cached upstream
    prefixes require an explicit future cache-lineage contract, not invented
    calls. Inference cost inside an external host remains its attestation.
    """
    if type(llm) is not GraphLLM: raise ValueError('original bounded Graph provider required')
    if getattr(llm, 'campaign_root', None) is not None:
        return _campaign_generation_outputs(llm)
    llm.valid()
    root = llm.root
    state_pin, state = _document(root / agent_graph.STATE)
    if state['cancelled'] or any(row['status'] != 'completed' for row in state['calls'].values()):
        raise ValueError('unresolved/cancelled generation cannot become a completed source result')
    steps = []
    for call_id, retained in state['calls'].items():
        call_pin, call = _document(root / 'calls' / (call_id + '.json'))
        if (agent_graph.digest(call) != retained['receipt_sha256'] or call['status'] != 'completed'
                or call['kind'] != 'model' or call['node_id'] != 'generate'
                or agent_graph.digest(call['result']) != call['result_sha256']):
            raise ValueError('original call ledger/result bytes differ')
        request_pin, request = _document(root / 'requests' / (call['attempt_id'] + '.json'))
        if request['sha256'] != agent_graph.digest({k: v for k, v in request.items() if k != 'sha256'}) or agent_graph.digest(request) != call['request_sha256']:
            raise ValueError('generation request differs from original reserved call')
        messages_pin = next(p for p in request['request']['input_artifacts'] if p['id'] == 'upstream-messages')
        _, raw = candidate._snapshot({k: messages_pin[k] for k in ('path', 'sha256')}, Path.cwd())
        messages = candidate._json(raw)
        steps.append({'stage': messages['generator_stage'], 'messages': messages['messages'],
            'value': deepcopy(call['result']['value']), 'transport': deepcopy(call['result']['transport']),
            'call': call_pin, 'request': request_pin, 'messages_pin': {k: messages_pin[k] for k in ('path', 'sha256')}})
    steps.sort(key=lambda s: s['stage'])
    if (len(steps) != llm.steps or [s['stage'] for s in steps] != list(range(llm.steps))
            or len(steps) < 4 or (len(steps) - 1) % 3):
        raise ValueError('complete fresh Analyst and coder/reviewer triplets required')
    if _document(root / agent_graph.STATE)[0] != state_pin:
        raise ValueError('provider ledger changed during source readback')
    llm.valid()
    return {'kind': 'agentrivet_generation_readback', 'graph_root': str(root), 'ledger': state_pin,
        'steps': steps, 'calls': state['usage']['calls'], 'output_token_reservations': state['usage']['reserved_output_tokens'],
        'internal_provider_usage_measured': False, 'independent_scientific_reviews': False}


def _campaign_generation_outputs(llm):
    """Bind ordinary Host results, real call receipts and original message inputs."""
    llm.valid(); contract=llm._campaign_contract(); children = llm._campaign_children(); steps = []; endings = []
    for index, root in enumerate(children):
        with state_io.file_lock(root/'state.lock'):
            spec, state = agent_graph._load(root)
            ledger, _ = _document(root/agent_graph.STATE)
            node = spec['nodes'][0]; agent_graph._artifact_checks(node)
            saved = agent_graph._result(root,state['nodes']['generate']['result'])
            expected = agent_graph._request(spec,state,node,saved['host_sha256'])
            if (saved['request'] != expected or saved['host_sha256']!=agent_graph.digest(contract['host_identity'])
                    or saved['result'].get('kind') != 'model_result'
                    or saved['result']['transport']['request_id'] != expected['request_id']):
                raise ValueError('ordinary source-role result differs from its exact Host request')
            call_id, retained = next(iter(state['calls'].items()))
            call_pin, call = _document(root/'calls'/(call_id+'.json'))
            if (agent_graph.digest(call) != retained['receipt_sha256'] or call['status'] != 'completed'
                    or call['kind'] != 'model' or call['attempt_id'] != saved['attempt_id']
                    or call['result'] != saved['result'] or agent_graph.digest(call['result']) != call['result_sha256']
                    or saved['call_receipts'] != [{'call_id':call_id,'sha256':retained['receipt_sha256']}]):
                raise ValueError('complete actual role call/result custody required')
            messages_pin = next((p for p in node['inputs'] if p['id'] in ('upstream-user-message','upstream-messages')), None)
            if messages_pin is None: raise ValueError('original role message input required')
            pin = {k:messages_pin[k] for k in ('path','sha256')}
            _, raw = candidate._snapshot(pin,Path.cwd()); document = candidate._json(raw)
            messages, role, brief = _presented_messages(node, document, llm)
            if (document['generator_stage'] != index or node['kind'] != 'model'
                    or node['role'] != 'proposer' or node['action'] != 'model'
                    or node['parameters']['model'] != llm.model
                    or node['parameters']['reasoning_effort'] != llm.effort
                    or node['parameters']['max_output_tokens'] != llm.cap
                    or node['parameters']['output_schema'] != document['graph_output_schema']
                    or {'id':'operation-contract',**llm.contract_pin} not in node['inputs']):
                raise ValueError('complete declared source-role/model/message contract required')
            attempt = root/state['nodes']['generate']['result']['path']
            request_pin, _ = _document(attempt)
            steps.append({'stage':index,'role':role,'messages':messages,'value':deepcopy(saved['result']['value']),
                'transport':deepcopy(saved['result']['transport']),'call':call_pin,'request':request_pin,
                'messages_pin':pin,'brief':brief,'graph_root':str(root),'graph_ledger':ledger})
            endings.append((root/agent_graph.STATE,ledger))
    if len(steps)!=llm.steps:
        raise ValueError('complete fresh Analyst and coder/reviewer history required')
    memory_history(steps)
    for path,pin in endings:
        if _document(path)[0]!=pin: raise ValueError('source-role ledger changed during readback')
    llm.valid()
    return {'kind':'agentrivet_generation_readback','graph_root':str(llm.root),'ledger':deepcopy(llm.contract_pin),
        'steps':steps,'calls':len(steps),'output_token_reservations':len(steps)*llm.cap,
        'internal_provider_usage_measured':False,'independent_scientific_reviews':False,
        'executor':'research_cycle.execute_graph','campaign_root':str(llm.campaign_root)}


def _presented_messages(node, document, llm):
    """Exact upstream messages of one retained role call, as presented to the model.

    Version 2 presents the system prompt as the model instruction (plus the
    fixed transport suffix) and the user message as the only upstream input;
    source custody stays in the operation contract. Version 1 (earlier
    retained calls) presented both messages and every source as inputs.
    """
    from .agentrivet_provider import SYSTEM_SUFFIX, NO_SYSTEM
    ids = [p['id'] for p in node['inputs']]
    if document.get('schema_version') == 1:
        if (ids[:2] != ['upstream-messages', 'operation-contract']
                or any({'id':f'source-{i}',**p} not in node['inputs'] for i,p in enumerate(llm.source_inputs))):
            raise ValueError('retained version-1 role call lacks its presented sources')
        return document['messages'], None, None
    if document.get('schema_version') != 2 or ids[:2] != ['upstream-user-message', 'operation-contract']:
        raise ValueError('original role message document version required')
    if ids[2:] not in ([], ['ravel-brief']):
        raise ValueError('a role call presents only its message, the operation contract and a RAVEL brief')
    instructions = node['parameters']['instructions']
    if document['system_present']:
        if not instructions.endswith(SYSTEM_SUFFIX):
            raise ValueError('presented role instruction differs from the original system message')
        system = instructions[:-len(SYSTEM_SUFFIX)]
        if hashlib.sha256(system.encode()).hexdigest() != document['system_sha256']:
            raise ValueError('presented role instruction differs from the original system message')
        messages = [{'role':'system','content':system},{'role':'user','content':document['user']}]
    else:
        if instructions != NO_SYSTEM + SYSTEM_SUFFIX: raise ValueError('presented role instruction changed')
        messages = [{'role':'user','content':document['user']}]
    brief = next(({k:p[k] for k in ('path','sha256')} for p in node['inputs'] if p['id']=='ravel-brief'), None)
    if brief is not None: candidate._snapshot(brief, Path.cwd())
    return messages, document['role'], brief


ROLE_CYCLE = ('coder', 'code_reviewer', 'physics_reviewer')


def _roles(steps):
    roles = [step.get('role') for step in steps]
    if all(role is None for role in roles):
        # Earlier retained histories: Analyst then complete triplets, by position.
        if len(steps) < 4 or (len(steps) - 1) % 3:
            raise ValueError('complete fresh Analyst and coder/reviewer triplets required')
        return ['analyst', *ROLE_CYCLE * ((len(steps) - 1) // 3)]
    if any(role is None for role in roles):
        raise ValueError('every role call must name its original role')
    return roles


def memory_history(steps):
    """Expected Memory lists from the actual role calls, in order.

    Each iteration is one coder call followed by both reviews, or by no review
    (a compile-gated iteration whose draft did not compile). Skipped reviews
    are ``None`` in Memory, as upstream stores them.
    """
    roles = _roles(steps)
    if not roles or roles[0] != 'analyst' or 'analyst' in roles[1:]:
        raise ValueError('one fresh Analyst call must come first')
    drafts, code, physics, skipped = [], [], [], []
    i = 1
    while i < len(roles):
        if roles[i] != 'coder':
            raise ValueError('original role order differs: each iteration starts with the coder')
        value = steps[i]['value']
        if type(value) is not dict or type(value.get('text')) is not str:
            raise ValueError('coder output text required')
        drafts.append(value['text'].strip()); i += 1
        if roles[i:i+2] == ['code_reviewer', 'physics_reviewer']:
            code.append({'__kind__': 'pydantic', '__class__': 'CodeReviewModel', 'data': steps[i]['value']})
            physics.append({'__kind__': 'pydantic', '__class__': 'PhysicsReviewModel', 'data': steps[i+1]['value']})
            i += 2
        elif i < len(roles) and roles[i] != 'coder':
            raise ValueError('original role order differs: reviews come in pairs after a draft')
        else:
            code.append(None); physics.append(None); skipped.append(len(drafts) - 1)
    if not drafts:
        raise ValueError('at least one coder draft required')
    return {'code_draft': drafts, 'code_review': code, 'physics_review': physics, 'skipped_reviews': skipped}


def verify_memory(data, steps, *, compile_gate, observed=None):
    """Memory equals the actual role history; skipped reviews need an observed failed compile.

    ``observed`` maps a draft's SHA-256 to its RAVEL check ``(returncode, text)``.
    Upstream ``build_result`` entries must equal those observations exactly.
    """
    history = memory_history(steps)
    for key in ('code_draft', 'code_review', 'physics_review'):
        if data.get(key) != history[key]:
            raise ValueError('Memory code/review history differs from actual Graph output')
    if data.get('iteration') != len(history['code_draft']):
        raise ValueError('Memory iteration differs from the actual coder calls')
    builds = data.get('build_result')
    if history['skipped_reviews'] and not compile_gate:
        raise ValueError('reviews may be skipped only by a compile-gated upstream loop')
    if builds is not None or history['skipped_reviews']:
        if not compile_gate or type(builds) is not list or len(builds) != len(history['code_draft']) or observed is None:
            raise ValueError('every compile-gated draft needs its RAVEL-observed compile result')
        for k, (draft, build) in enumerate(zip(history['code_draft'], builds)):
            check = observed.get(hashlib.sha256(draft.encode('utf-8')).hexdigest())
            expected = None if check is None else {'__kind__': 'pydantic', '__class__': 'BuildResult',
                                                   'data': {'returncode': check[0], 'output': check[1]}}
            if build != expected:
                raise ValueError('upstream compile result differs from the RAVEL-observed compile')
            if (k in history['skipped_reviews']) != (check[0] != 0):
                raise ValueError('reviews were skipped exactly when the observed compile failed')
    return history


def selection(data, history, compiled):
    """Selected draft: upstream acceptance, else the last RAVEL-observed compiled draft, else the last."""
    drafts = history['code_draft']
    if data.get('accepted_code') is not None:
        if data['accepted_code'] != drafts[-1]: raise ValueError('upstream accepted marker is not the last draft')
        return {'draft_index': len(drafts) - 1, 'basis': 'upstream_accepted'}
    for k in range(len(drafts) - 1, -1, -1):
        if compiled(drafts[k]):
            return {'draft_index': k, 'basis': 'last_observed_compile'}
    return {'draft_index': len(drafts) - 1, 'basis': 'last_draft'}


@contextmanager
def bind_compile(core, session):
    """Route a compile-gated core's build_routine through RAVEL's observed compile.

    The original module-level name is restored afterwards. The binding runs
    RAVEL's own service with the no-subprocess guard suspended; every other
    upstream call stays guarded.
    """
    original = getattr(core, 'build_routine', None)
    if original is None:
        yield None
        return
    build_module = sys.modules.get(original.__module__)
    result_class = getattr(build_module, 'BuildResult', None)
    if result_class is None or session is None:
        def refused(code):
            raise agentrivet_pins.UpstreamExecutionRefused('no approved RAVEL compile check for this construction')
        binding = refused
    else:
        def binding(code):
            with agentrivet_pins.ravel_service():
                returncode, text = session.build_result(code)
            with agentrivet_pins.upstream_call():
                return result_class(returncode=returncode, output=text)
    core.build_routine = binding
    try:
        yield binding
    finally:
        core.build_routine = original


def prepare_source_study(core, roles, llm, memory_module, memory, *, source_pins, memory_pin,
                         routine, assets, output_dir, review_policy, approval_mode='physicist',
                         compile_gate=False, observed=None, draft_compiled=None):
    """Original loop outputs -> raw Memory/.cc -> ordinary source-study input.

    This never invokes the loop or a scientific worker. It verifies that every
    returned Memory declaration/code/review equals the actual Graph output,
    preserves the full raw generator transcript, and prepares the EXISTING
    agentrivet-source adapter. Native source closure/build/review/event planning
    continues through agentrivet_source.prepare_build, never upstream approval.
    """
    from ravel.physics import agentrivet_source
    binding = inspect_binding(core, roles, source_pins=source_pins)
    declared = {(p['path'], p['sha256']) for p in llm.source_inputs}
    if (memory_pin['path'], memory_pin['sha256']) not in declared:
        raise ValueError('original Memory source must be a normal provider input before generation')
    _, _, compiled = _module(memory_module, memory_pin, 'memory.py')
    agentrivet_pins.admit_member_pins({'memory': memory_pin})
    original = _code(compiled, 'Memory')
    if memory.__class__ is not memory_module.Memory:
        raise ValueError('original loaded upstream Memory required')
    for member in original.co_consts:
        if isinstance(member, CodeType):
            loaded = getattr(memory_module.Memory, member.co_name, None)
            loaded = getattr(loaded, '__func__', loaded)
            if not inspect.isfunction(loaded) or not _same_code(loaded.__code__, member):
                raise ValueError('original Memory serialization method changed')
    data = memory.to_dict()
    transcript = generation_outputs(llm)
    steps = transcript['steps']
    model = data.get('analysis_model')
    if (type(model) is not dict or model.get('__class__') != 'AnalysisModel'
            or model.get('data') != steps[0]['value']):
        raise ValueError('Memory Analyst/iteration does not match actual Graph outputs')
    history = verify_memory(data, steps, compile_gate=compile_gate, observed=observed)
    if (type(data.get('paper_text')) is not str or not data['paper_text'].strip()
            or routine != memory.rivetName() or ('accepted_code' in data and data['accepted_code'] != data['code_draft'][-1])):
        raise ValueError('exact paper component/routine/current draft required')
    chosen = selection(data, history, draft_compiled or (lambda code: False))
    selected_code = data['code_draft'][chosen['draft_index']]
    original_prompt = core.ReviewLoop._build_analyst_prompt(None, memory)
    if steps[0]['messages'] != [{'role': 'system', 'content': roles['analyst'].ANALYST_PROMPT},
                                {'role': 'user', 'content': original_prompt}]:
        raise ValueError('paper/HEPData Memory differs from actually presented Analyst input')
    if type(assets) is not list or len(assets) > 32: raise ValueError('bounded explicit external asset inputs required')
    for asset in assets: candidate._snapshot(asset['input'], Path.cwd())
    out = Path(output_dir).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError('fresh original-output materialization directory required')
    # Recheck every source and provider proof before writing; raw output is
    # source proposal only and does not carry any upstream accepted marker.
    if inspect_binding(core, roles, source_pins=source_pins) != binding or generation_outputs(llm) != transcript or memory.to_dict() != data:
        raise ValueError('generation/source/Memory changed before materialization')
    out.mkdir(parents=True)
    raw = out / 'raw'; raw.mkdir()
    generated = {'binding': binding, 'memory_source': memory_pin, 'transcript': transcript,
        'upstream_accepted_marker': data.get('accepted_code') is not None, 'selection': chosen,
        'ordinary_scientific_acceptance': False, 'provider_runtime_qualified': False}
    campaign = getattr(llm, 'campaign_root', None) is not None
    intended = {}
    if campaign:
        # New ordinary campaign route binds each intended emission before the
        # first write. Never treat a changed post-write reread as its baseline.
        intended = {routine+'.cc':selected_code.encode('utf-8'),
            'paper.txt':data['paper_text'].encode('utf-8'),
            'memory.json':(json.dumps(data,indent=2,allow_nan=False)+'\n').encode(),
            'generation.json':(json.dumps(generated,indent=2,allow_nan=False)+'\n').encode()}
        commitments = {name:{'path':str(raw/name),'sha256':hashlib.sha256(value).hexdigest()}
                       for name,value in intended.items()}
    (raw / (routine + '.cc')).write_text(selected_code, encoding='utf-8')
    (raw / 'paper.txt').write_text(data['paper_text'], encoding='utf-8')
    state_io.atomic_json(raw / 'memory.json', data)
    state_io.atomic_json(raw / 'generation.json', generated)
    if campaign:
        for name,expected in intended.items():
            if candidate._snapshot(commitments[name],out)[1]!=expected:
                raise ValueError('intended original-loop emission changed before consumption')
        files = {name:commitments[filename] for name,filename in
            [('translation_unit',routine+'.cc'),('memory','memory.json'),('paper','paper.txt')]}
        generation_pin = commitments['generation.json']
    else:
        files = {name: _document(raw / filename)[0] if name == 'memory' else
            {'path': str(raw / filename), 'sha256': hashlib.sha256((raw / filename).read_bytes()).hexdigest()}
            for name, filename in [('translation_unit', routine + '.cc'), ('memory', 'memory.json'), ('paper', 'paper.txt')]}
        generation_pin = _document(raw / 'generation.json')[0]
    request = {'schema_version': 1, 'routine': routine, **files, 'assets': deepcopy(assets)}
    if chosen['draft_index'] != len(data['code_draft']) - 1:
        request['selection'] = chosen
    prepared = agentrivet_source.prepare_source_study(request, base_dir=out, output_dir=out / 'source-study',
        review_policy=review_policy, approval_mode=approval_mode)
    if campaign:
        for name,expected in intended.items():
            if candidate._snapshot(commitments[name],out)[1]!=expected:
                raise ValueError('intended original-loop emission changed during source preparation')
        if generation_outputs(llm)!=transcript or memory.to_dict()!=data:
            raise ValueError('original-loop evidence changed during source preparation')
    return {'kind': 'agentrivet_original_loop_to_ordinary_source', 'raw_request': request,
        'generation': generation_pin, 'source_study': prepared,
        'whole_source_and_domain_review_still_required': True, 'build_event_execution_authorized': False,
        'upstream_reviews_carried': [], 'physics_validated': False}
