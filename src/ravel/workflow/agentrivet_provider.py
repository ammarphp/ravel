"""AgentRivet-compatible LLM interface backed by the existing Graph.

Upstream callers keep their Analyst/Coder/reviewer prompts and ReviewLoop. The
explicit dispatcher consumes a prepared ordinary external request and returns
its real response path; this module supplies no SDK, credential or runner.
"""
from pathlib import Path
from copy import deepcopy
import inspect,hashlib
import json,time
from ravel.physics import agentrivet_candidate as candidate
from ravel.workflow import agent_graph, agentrivet_pins
from ravel.workflow.state_io import atomic_json,read_json


# The upstream system prompt becomes the model's instruction verbatim, followed
# by this fixed transport note. Readback strips exactly this suffix.
SYSTEM_SUFFIX = ('\n\n---\nRAVEL transport: the user input for this instruction is the "user" field of the '
                 'upstream-user-message input. A ravel-brief input, when present, is RAVEL construction context '
                 'for this role; use it where it does not change the required output format. Return the requested '
                 'schema; raw code goes in the text field. These outputs are advisory producer annotations, never '
                 'RAVEL scientific votes.')
NO_SYSTEM = 'No original system instruction was supplied for this call.'
MAX_BRIEF = 512 * 1024
# One Analyst plus up to three initial rounds and two repairs of three role calls.
MAX_CAMPAIGN_CALLS = 16


def graph_output_schema(original):
    """Adapt local Pydantic refs/nullable fields to the existing finite Graph.

    Object fields become explicit, including nullable fields that the upstream
    model could otherwise fill with defaults. No output value is filled here.
    Other unions, external refs and recursive schemas remain unsupported.
    """
    from ravel.workflow.agent_host import _schema, _same_json
    if type(original) is not dict:raise ValueError('literal upstream output schema required')
    definitions=original.get('$defs',{})
    if type(definitions) is not dict:raise ValueError('local schema definitions required')
    def convert(source,trail=(),depth=0):
        if depth>32 or type(source) is not dict:raise ValueError('bounded finite output schema required')
        result=deepcopy(source);result.pop('$defs',None);result.pop('default',None)
        if '$ref' in result:
            ref=result.pop('$ref')
            if type(ref) is not str or not ref.startswith('#/$defs/') or ref[len('#/$defs/'):] not in definitions or ref in trail:
                raise ValueError('nonrecursive local output reference required')
            target=convert(definitions[ref[len('#/$defs/'):]],(*trail,ref),depth+1)
            if set(result)-{'title','description'}:raise ValueError('unsupported referenced schema override')
            result={**target,**result}
        if 'anyOf' in result:
            variants=result.pop('anyOf')
            if type(variants) is not list or len(variants)!=2 or sum(v=={'type':'null'} for v in variants)!=1:
                raise ValueError('only explicit nullable output unions are supported')
            other=convert(next(v for v in variants if v!={'type':'null'}),trail,depth+1)
            if set(result)-{'title','description'} or type(other.get('type')) is not str:
                raise ValueError('unsupported nullable output schema')
            result={**other,**result,'type':[other['type'],'null']}
            # A type union alone cannot preserve nullable enum/const schemas:
            # those constraints would otherwise reject the explicit null arm.
            # Keep the nonnull intersection, then add precisely that null arm.
            if 'enum' in result and (type(result['enum']) is not list or not result['enum']):
                raise ValueError('nullable output enum requires literal values')
            if 'const' in result:
                constant=result.pop('const')
                result['enum']=([constant] if 'enum' not in result else
                    [value for value in result['enum'] if _same_json(value,constant)])
            if 'enum' in result and not any(value is None for value in result['enum']):
                result['enum'].append(None)
        types=result.get('type');types=[types] if type(types) is str else types
        if type(types) is not list:raise ValueError('explicit output types required')
        if 'object' in types:
            properties=result.get('properties')
            if type(properties) is not dict:raise ValueError('literal output properties required')
            result['properties']={key:convert(value,trail,depth+1) for key,value in properties.items()}
            result['required']=list(properties);result['additionalProperties']=False
        if 'array' in types:result['items']=convert(result.get('items'),trail,depth+1)
        return result
    schema=convert(original);_schema(schema)
    return schema


class GraphLLM:
    """Duck-compatible valid()/generate(), with one cumulative graph budget.

    Upstream generator reviewers remain producer annotations (Graph proposer),
    never independent RAVEL scientific review roles. Text is transported in a
    JSON envelope; that explicit adaptation is not the upstream raw protocol.
    """
    def __init__(self, graph_root, *, model, reasoning_effort, max_calls,
                 max_output_tokens, max_wall_seconds, dispatcher, dispatcher_pin,
                 source_inputs):
        if (not isinstance(model,str) or not model.strip() or not isinstance(reasoning_effort,str)
                or type(max_calls) is not int or not 1<=max_calls<=10
                or type(max_output_tokens) is not int or not 16<=max_output_tokens<=32000
                or type(max_wall_seconds) is not int or not 1<=max_wall_seconds<=7200
                or not callable(dispatcher) or type(source_inputs) is not list
                or not 1<=len(source_inputs)<=64):
            raise ValueError('bounded explicit Graph provider contract required')
        path,_=candidate._snapshot(dispatcher_pin,Path.cwd())
        actual=Path(inspect.getsourcefile(dispatcher) or '').absolute()
        if actual!=path:raise ValueError('dispatcher must come from its explicit source pin')
        root=Path(graph_root).absolute()
        if root.exists() or any(p.is_symlink() for p in (root,*root.parents)):
            raise ValueError('fresh Graph provider session required')
        self.root=root;self.dispatcher=dispatcher
        self.dispatcher_pin={'path':str(path),'sha256':dispatcher_pin['sha256']}
        self.source_inputs=[];seen={str(path)}
        for pin in source_inputs:
            source,_=candidate._snapshot(pin,Path.cwd())
            if str(source) in seen:raise ValueError('distinct declared source inputs required')
            seen.add(str(source))
            self.source_inputs.append({'path':str(source),'sha256':pin['sha256']})
        implementation=Path(__file__).absolute()
        if str(implementation) not in seen:
            self.source_inputs.append({'path':str(implementation),'sha256':hashlib.sha256(implementation.read_bytes()).hexdigest()})
        self.model=model;self.effort=reasoning_effort;self.cap=max_output_tokens;self.calls=max_calls;self.wall=max_wall_seconds
        self.steps=0

    def valid(self):
        # Source contract readiness only; no hidden upstream models.retrieve.
        if getattr(self, 'campaign_root', None) is not None:
            self._campaign_contract()
            return True
        candidate._snapshot(self.dispatcher_pin,Path.cwd())
        for pin in self.source_inputs:candidate._snapshot(pin,Path.cwd())
        return True

    def generate(self,messages,output_model=None):
        # RAVEL's own dispatch (Graph, Host, transport) runs with the upstream
        # no-subprocess guard suspended; the upstream output model is guarded.
        with agentrivet_pins.ravel_service():
            value=self._generate(messages,output_model)
        return value['text'] if output_model is None else output_model.model_validate(value)

    def _generate(self,messages,output_model=None):
        if (type(messages) is not list or not 1<=len(messages)<=2
                or any(type(r) is not dict or set(r)!={'role','content'} or r['role'] not in ('system','user') or type(r['content']) is not str for r in messages)
                or [r['role'] for r in messages] not in (['user'],['system','user'])):
            raise ValueError('exact upstream system/user message shape required')
        if getattr(self, 'campaign_root', None) is not None:
            return self._campaign_generate(messages, output_model)
        if self.steps>=self.calls:raise ValueError('cumulative upstream Graph call ceiling exhausted')
        self.valid()
        if self.steps:
            state=agent_graph.status(self.root)
            if state['nodes']['generate']['status']!='completed':
                raise ValueError('unresolved provider outcome must be reconciled; no retry/reset')
        else:self.root.parent.mkdir(parents=True,exist_ok=True)
        if not self.steps and self.root.exists():
            raise ValueError('unresolved provider outcome must be reconciled; no retry/reset')
        context=self.root.parent/(self.root.name+'-message-'+str(self.steps)+'.json')
        if context.exists():raise ValueError('provider message output must be fresh')
        with agentrivet_pins.upstream_call():
            original_schema=({'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}
                    if output_model is None else output_model.model_json_schema())
        schema=graph_output_schema(original_schema)
        atomic_json(context,{'schema_version':1,'messages':messages,'generator_stage':self.steps,
            'original_output_schema':original_schema,'graph_output_schema':schema,
            'transport_adaptation':'Explicit JSON text envelope or finite local-ref/nullable schema with all fields required',
            'upstream_review_is_advisory':True,'independent_scientific_review':False})
        node={'id':'generate','kind':'model','role':'proposer','depends_on':[],
            'inputs':[{'id':'upstream-messages','path':str(context),'sha256':hashlib.sha256(context.read_bytes()).hexdigest()},
                      {'id':'dispatcher-source',**self.dispatcher_pin},
                      *[{'id':'source-'+str(i),**pin} for i,pin in enumerate(self.source_inputs)]],
            'packet':None,'action':'external','max_attempts':1,'parameters':{
                'instructions':'Use the exact supplied system/user messages as the generation instruction. Return the requested schema; raw code uses the text field. Generator reviews are advisory and grant no RAVEL scientific authority.',
                'model':self.model,'reasoning_effort':self.effort,'max_output_tokens':self.cap,'output_schema':schema}}
        spec={'schema_version':1,'graph_id':'agentrivet-provider','budget':{
            'max_nodes':1,'max_calls':self.calls,'max_output_tokens':self.calls*self.cap,
            'max_wall_seconds':self.wall,'max_reworks':self.calls-1},'nodes':[node]}
        if not self.steps:agent_graph.create(self.root,spec)
        else:agent_graph.revise(self.root,spec,reason='Next upstream generation stage; retained cumulative budget and old outputs')
        prepared=agent_graph.prepare_external(self.root,'generate')
        # There is no retry. A dispatch exception leaves the existing Graph's
        # ambiguous reservation intact and blocks later steps.
        response=self.dispatcher(prepared)
        self.valid()
        agent_graph.deliver_external(self.root,'generate',response)
        state=agent_graph.status(self.root);reference=state['nodes']['generate']['result']
        saved=read_json(self.root/reference['path']);value=saved['result']['value']
        self.steps+=1
        return value

    @classmethod
    def campaign(cls, graph_root, campaign_root, host, *, model, reasoning_effort,
                 max_calls, max_output_tokens, max_wall_seconds, source_inputs):
        """Original role interface through the ordinary charged research executor.

        Each role gets an immutable one-call child. The retained operation
        contract/count/deadline and the campaign reservations both apply; no
        external dispatcher, Graph revision or parallel scheduler is introduced.
        Existing external GraphLLM callers keep their original path unchanged.
        """
        from . import research_cycle
        from .agent_host import AgentHost
        if (type(host) is not AgentHost or type(model) is not str or not model.strip()
                or type(reasoning_effort) is not str or not reasoning_effort.strip()
                or type(max_calls) is not int or not 4 <= max_calls <= MAX_CAMPAIGN_CALLS
                or type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 32000
                or type(max_wall_seconds) is not int or not max_calls <= max_wall_seconds <= 7200
                or type(source_inputs) is not list or not 1 <= len(source_inputs) <= 126):
            raise ValueError('explicit finite campaign provider/Host contract required')
        obj = cls.__new__(cls)
        obj.root = research_cycle._ordinary(graph_root)
        obj.campaign_root = research_cycle._ordinary(campaign_root)
        _, state = research_cycle._load(obj.campaign_root)
        obj.host = host; obj.model = model; obj.effort = reasoning_effort
        obj.calls = max_calls; obj.cap = max_output_tokens; obj.wall = max_wall_seconds
        obj.source_inputs = []; seen = set()
        for pin in source_inputs:
            path, raw = research_cycle._bounded_source_snapshot(pin['path'], 8*1024**2)
            candidate._closed(pin, {'path','sha256'})
            if hashlib.sha256(raw).hexdigest() != pin['sha256'] or str(path) in seen:
                raise ValueError('distinct authenticated campaign provider inputs required')
            seen.add(str(path)); obj.source_inputs.append({'path':str(path),'sha256':pin['sha256']})
        implementation = Path(__file__).absolute()
        if str(implementation) not in seen:
            obj.source_inputs.append({'path':str(implementation),'sha256':hashlib.sha256(implementation.read_bytes()).hexdigest()})
        if len(obj.source_inputs)>126:
            raise ValueError('complete provider inputs exceed the declared finite population')
        contract = {'schema_version':1,'kind':'agentrivet-campaign-provider',
            'campaign_root':str(obj.campaign_root),'campaign_contract_sha256':agent_graph.digest(state['contract']),
            'model':model,'reasoning_effort':reasoning_effort,'max_calls':max_calls,
            'max_output_tokens':max_output_tokens,'max_wall_seconds':max_wall_seconds,
            'source_inputs':obj.source_inputs,'host_identity':host.identity}
        raw = (json.dumps(contract,indent=2,allow_nan=False)+'\n').encode()
        obj.contract_pin = {'path':str(obj.root/'provider-contract.json'),'sha256':hashlib.sha256(raw).hexdigest()}
        obj.role_prompts = {}; obj.brief_source = None; obj.observer = None; obj.last_draft = None
        if not obj.root.exists():
            obj.root.mkdir(parents=True)
            atomic_json(obj.root/'provider-contract.json',contract)
        obj._campaign_contract()
        obj.steps = len(obj._campaign_children())
        return obj

    @classmethod
    def retained_campaign(cls, graph_root, campaign_root):
        """Read an existing source-role history without a Host or new dispatch.

        The original contract pin comes from the retained first Graph input,
        never a fresh baseline hash of mutable provider-contract bytes. Actual
        call receipts must use that original Host identity. This read-only
        interface cannot generate, reset or acquire execution authority.
        """
        from . import research_cycle
        obj=cls.__new__(cls); obj.root=research_cycle._ordinary(graph_root)
        obj.campaign_root=research_cycle._ordinary(campaign_root); obj.host=None
        spec,_=agent_graph._load(obj.root/'stage-00')
        ref=next(p for p in spec['nodes'][0]['inputs'] if p['id']=='operation-contract')
        obj.contract_pin={k:ref[k] for k in ('path','sha256')}
        if obj.contract_pin['path']!=str(obj.root/'provider-contract.json'):
            raise ValueError('retained original operation contract path required')
        _,raw=research_cycle._bounded_source_snapshot(obj.contract_pin['path'],2*1024**2)
        if hashlib.sha256(raw).hexdigest()!=obj.contract_pin['sha256']:
            raise ValueError('retained original operation contract changed')
        contract=candidate._json(raw)
        candidate._closed(contract,{'schema_version','kind','campaign_root','campaign_contract_sha256',
            'model','reasoning_effort','max_calls','max_output_tokens','max_wall_seconds','source_inputs','host_identity'})
        if contract['kind']!='agentrivet-campaign-provider' or contract['campaign_root']!=str(obj.campaign_root):
            raise ValueError('retained source-role campaign differs')
        obj.model=contract['model']; obj.effort=contract['reasoning_effort']
        obj.calls=contract['max_calls']; obj.cap=contract['max_output_tokens']; obj.wall=contract['max_wall_seconds']
        obj.source_inputs=deepcopy(contract['source_inputs'])
        obj._campaign_contract(); obj.steps=len(obj._campaign_children())
        return obj

    def bind_construction(self, role_prompts, *, brief_source=None, observer=None):
        """Name each original role by its exact system prompt; add RAVEL briefs and draft checks.

        ``brief_source(role, stage, last_draft)`` returns a JSON-able brief or
        None. ``observer(code)`` runs RAVEL's approved construction checks on
        each new coder draft. Neither changes an upstream message.
        """
        if type(role_prompts) is not dict or not role_prompts:
            raise ValueError('original role prompts required')
        prompts = {}
        for role, prompt in role_prompts.items():
            if type(prompt) is not str or not prompt:
                raise ValueError('literal original role prompt required')
            digest = hashlib.sha256(prompt.encode()).hexdigest()
            if digest in prompts: raise ValueError('original role prompts must be distinct')
            prompts[digest] = role
        if (brief_source is not None and not callable(brief_source)) or (observer is not None and not callable(observer)):
            raise ValueError('callable brief source and observer required')
        self.role_prompts = prompts; self.brief_source = brief_source; self.observer = observer
        return self

    def _campaign_contract(self):
        from . import research_cycle
        _, raw = research_cycle._bounded_source_snapshot(self.contract_pin['path'], 2*1024**2)
        if hashlib.sha256(raw).hexdigest() != self.contract_pin['sha256']:
            raise ValueError('original campaign provider contract changed')
        contract = candidate._json(raw)
        if ({'model':self.model,'reasoning_effort':self.effort,'max_calls':self.calls,
             'max_output_tokens':self.cap,'max_wall_seconds':self.wall,'source_inputs':self.source_inputs,
             'campaign_root':str(self.campaign_root)} != {k:contract[k] for k in
             ('model','reasoning_effort','max_calls','max_output_tokens','max_wall_seconds','source_inputs','campaign_root')}):
            raise ValueError('in-memory provider declaration differs from the original contract')
        _, state = research_cycle._load(self.campaign_root)
        if (agent_graph.digest(state['contract']) != contract['campaign_contract_sha256']
                or self.host is not None and self.host.identity != contract['host_identity']):
            raise ValueError('original campaign/Host binding changed')
        for pin in self.source_inputs:
            _, raw = research_cycle._bounded_source_snapshot(pin['path'], 8*1024**2)
            if hashlib.sha256(raw).hexdigest() != pin['sha256']:
                raise ValueError('campaign provider source changed')
        return contract

    def _campaign_children(self):
        from . import research_cycle
        children = sorted(self.root.glob('stage-*'))
        if ([p.name for p in children] != [f'stage-{i:02d}' for i in range(len(children))]
                or len(children) > self.calls or any(not p.is_dir() or p.is_symlink() for p in children)):
            raise ValueError('complete contiguous original role Graph census required')
        for child in children:
            spec, state = agent_graph._load(child)
            _, campaign = research_cycle._load(self.campaign_root)
            research_cycle.validate_graph_reservation(campaign, child, spec)
            if (len(spec['nodes']) != 1 or spec['nodes'][0]['id'] != 'generate'
                    or state['cancelled'] or state['nodes']['generate']['status'] != 'completed'
                    or state['usage']['calls'] != 1 or len(state['calls']) != 1
                    or any(r['status'] != 'completed' for r in state['calls'].values())):
                raise ValueError('unresolved role outcome must be reconciled; no retry/reset')
        return children

    def _campaign_generate(self, messages, output_model):
        from .state_io import file_lock
        with file_lock(self.root/'provider.lock', blocking=False):
            return self._campaign_generate_locked(messages, output_model)

    def _campaign_generate_locked(self, messages, output_model):
        from . import research_cycle
        if self.host is None: raise ValueError('retained source-role readback cannot dispatch')
        self.valid()
        children = self._campaign_children()
        if len(children) != self.steps or self.steps >= self.calls:
            raise ValueError('original operation call count changed or exhausted')
        # The deadline starts with the first actual child, and cannot be reset
        # by reinstantiating the interface between native feedback rounds.
        started = None
        if children:
            _, first = agent_graph._load(children[0]); started = first['started_epoch']
        slice_seconds = self.wall // self.calls
        if started is not None:
            slice_seconds = min(slice_seconds, int(started + self.wall - time.time()))
        if slice_seconds < 1: raise ValueError('original provider wall-time allowance exhausted')
        with agentrivet_pins.upstream_call():
            original = ({'type':'object','properties':{'text':{'type':'string'}},'required':['text'],'additionalProperties':False}
                        if output_model is None else output_model.model_json_schema())
        schema = graph_output_schema(original)
        system = messages[0]['content'] if len(messages) == 2 else None
        user = messages[-1]['content']
        role = None
        if self.role_prompts:
            role = self.role_prompts.get(hashlib.sha256(system.encode()).hexdigest()) if system is not None else None
            if role is None: raise ValueError('upstream message matches no bound original role instruction')
        instructions = (system + SYSTEM_SUFFIX) if system is not None else NO_SYSTEM + SYSTEM_SUFFIX
        message_path = self.root/f'messages-{self.steps:02d}.json'
        document = {'schema_version':2,'generator_stage':self.steps,'role':role,'system_present':system is not None,
            'system_sha256':None if system is None else hashlib.sha256(system.encode()).hexdigest(),'user':user,
            'original_output_schema':original,'graph_output_schema':schema,
            'upstream_review_is_advisory':True,'independent_scientific_review':False}
        if message_path.exists(): raise ValueError('unresolved role preparation is retained; no repeat dispatch')
        pin = self._write(message_path, document)
        inputs = [{'id':'upstream-user-message',**pin},{'id':'operation-contract',**self.contract_pin}]
        brief = self.brief_source(role, self.steps, self.last_draft) if (self.brief_source is not None and role) else None
        if brief is not None:
            brief_path = self.root/f'brief-{self.steps:02d}.json'
            if brief_path.exists(): raise ValueError('unresolved role brief is retained; no repeat dispatch')
            inputs.append({'id':'ravel-brief',**self._write(brief_path, brief, MAX_BRIEF)})
        node = {'id':'generate','kind':'model','role':'proposer','depends_on':[],'inputs':inputs,
            'packet':None,'action':'model','max_attempts':1,'parameters':{
                'instructions':instructions,'model':self.model,'reasoning_effort':self.effort,
                'max_output_tokens':self.cap,'output_schema':schema}}
        spec = {'schema_version':1,'graph_id':f'agentrivet-role-{self.steps:02d}',
            'budget':{'max_nodes':1,'max_calls':1,'max_output_tokens':self.cap,
                      'max_wall_seconds':slice_seconds,'max_reworks':0},'nodes':[node]}
        child = self.root/f'stage-{self.steps:02d}'
        research_cycle.execute_graph(self.campaign_root, child, spec, self.host)
        self.valid(); self._campaign_children()
        _, state = agent_graph._load(child)
        saved = agent_graph._result(child, state['nodes']['generate']['result'])
        value = saved['result']['value']
        self.steps += 1
        if role == 'coder':
            draft = value['text'].strip() if isinstance(value, dict) and isinstance(value.get('text'), str) else None
            if draft:
                self.last_draft = draft
                if self.observer is not None: self.observer(draft)
        return value

    @staticmethod
    def _write(path, document, maximum=8*1024**2):
        from . import research_cycle
        raw = (json.dumps(document,indent=2,allow_nan=False)+'\n').encode()
        if len(raw) > maximum: raise ValueError('bounded role input required')
        pin = {'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()}
        atomic_json(path, document)
        _, consumed = research_cycle._bounded_source_snapshot(path, 8*1024**2)
        if consumed != raw: raise ValueError('intended role input bytes changed before dispatch')
        return pin
