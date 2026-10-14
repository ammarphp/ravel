"""Own source-role fixture; no upstream GPL bodies, SDKs or scientific job."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
from ravel.workflow import agent_host, research_cycle, agentrivet_pins, agentrivet_runtime
from ravel.workflow.state_io import atomic_json, read_json
from test_agentrivet_candidate import pin, MODEL, CODE
from test_agentrivet_source import review_wrapper
from test_research_cycle import contract
from test_task_completion import goal

CORE = '''def make_llm(provider,model):
    raise RuntimeError("No fixture SDK dispatch")
class Agent:
    def __init__(self,llm,system_prompt=None,output_model=None):
        self.llm=llm;self.system_prompt=system_prompt;self.output_model=output_model
        assert llm.valid()
    def run(self,prompt):
        return self.llm.generate([{"role":"system","content":self.system_prompt},{"role":"user","content":prompt}],self.output_model)
class ReviewLoop:
    def __init__(self,analyst,coder,code_reviewer,physics_reviewer,max_iterations=3):
        self.analyst=analyst;self.coder=coder;self.code_reviewer=code_reviewer;self.physics_reviewer=physics_reviewer;self.max_iterations=max_iterations
    def _build_analyst_prompt(self,memory): return memory.get("paper_text")
    def _build_coder_prompt(self,memory): return "Own code prompt: "+str(memory.to_dict())
    def _build_code_reviewer_prompt(self,memory): return memory.get("code_draft")[-1]
    def _build_physics_reviewer_prompt(self,memory): return memory.get("code_draft")[-1]
    def run(self,memory):
        memory.set("analysis_model",self.analyst.run(self._build_analyst_prompt(memory)))
        for i in range(self.max_iterations):
            memory.set("iteration",i+1)
            memory.append("code_draft",self.coder.run(self._build_coder_prompt(memory)).strip())
            memory.append("code_review",self.code_reviewer.run(self._build_code_reviewer_prompt(memory)))
            memory.append("physics_review",self.physics_reviewer.run(self._build_physics_reviewer_prompt(memory)))
            if memory.get("code_review")[-1].approved:
                memory.set("accepted_code",memory.get("code_draft")[-1]);break
        return memory
'''
MEMORY = '''from .analyst_agent import AnalysisModel
from .code_reviewer_agent import CodeReviewModel
from .physics_reviewer_agent import PhysicsReviewModel
class Memory:
    def __init__(self,cache_path=""): self.data={}
    def set(self,key,value): self.data[key]=value
    def get(self,key,default=None): return self.data.get(key,default)
    def has(self,key): return key in self.data
    def append(self,key,value): self.data.setdefault(key,[]).append(value)
    def item_length(self,key): return len(self.data.get(key,[]))
    def rivetName(self): return "TEST"
    def to_dict(self):
        def encode(v):
            if isinstance(v,(AnalysisModel,CodeReviewModel,PhysicsReviewModel)):
                return {"__kind__":"pydantic","__class__":type(v).__name__,"data":v.model_dump()}
            if isinstance(v,list): return [encode(x) for x in v]
            return v
        return {k:encode(v) for k,v in self.data.items()}
    @classmethod
    def from_dict(cls,value):
        models={"AnalysisModel":AnalysisModel,"CodeReviewModel":CodeReviewModel,"PhysicsReviewModel":PhysicsReviewModel}
        def decode(v):
            if isinstance(v,dict) and v.get("__kind__")=="pydantic": return models[v["__class__"]].model_validate(v["data"])
            if isinstance(v,list): return [decode(x) for x in v]
            return v
        m=cls();m.data={k:decode(v) for k,v in value.items()};return m
'''
MODELS = '''from copy import deepcopy
class OwnModel:
    schema={}
    def __init__(self,value): self.value=deepcopy(value)
    def __getattr__(self,name): return self.value[name]
    @classmethod
    def model_validate(cls,value): return cls(value)
    @classmethod
    def model_json_schema(cls): return deepcopy(cls.schema)
    def model_dump(self,**kwargs): return deepcopy(self.value)
'''


def schema(value):
    if value is None:return {'type':'null'}
    if type(value) is bool:return {'type':'boolean'}
    if type(value) is str:return {'type':'string'}
    if type(value) in (int,float):return {'type':'number'}
    if type(value) is list:return {'type':'array','items':schema(value[0]) if value else {'type':'string'}}
    return {'type':'object','properties':{k:schema(v) for k,v in value.items()},'required':list(value),'additionalProperties':False}

REVIEW={'approved':True,'summary':'Own source fixture only','blockers':[],'revision_focus':None}
PHYSICS={'summary':'Own diagnostic annotation','advisories':[],'revision_focus':None}


def fixture_files():
    files={'agentrivet/__init__.py':'# Own isolated source fixture\n','agentrivet/core.py':CORE,
        'agentrivet/memory.py':MEMORY,'agentrivet/fixture_models.py':MODELS,
        'pyproject.toml':'[project]\nname="own-role-fixture"\nversion="1.0"\n','COPYING':'Own test source; no third-party GPL body.\n'}
    values={'analyst':MODEL,'code_reviewer':REVIEW,'physics_reviewer':PHYSICS}
    for role,(filename,factory,prompt,model) in agentrivet_runtime.ROLES.items():
        definition='' if model is None else f'class {model}(OwnModel):\n    schema={schema(values[role])!r}\n'
        files['agentrivet/'+filename]=f'from .core import Agent,make_llm\nfrom .fixture_models import OwnModel\n{prompt}="Own {role} instruction"\n{definition}def {factory}(provider,model):\n    return Agent(make_llm(provider,model),{prompt},{model or "None"})\n'
    return files


FIXTURE_COMMIT='own-role-fixture'


@pytest.fixture(autouse=True)
def allow_own_source_census(monkeypatch):
    """Admit this own fixture tree as one extra census; real commits stay pinned."""
    census={name:hashlib.sha256(text.encode()).hexdigest() for name,text in fixture_files().items()}
    monkeypatch.setitem(agentrivet_pins.ALLOWED,FIXTURE_COMMIT,{'label':'own test fixture','files':census})


def original_fixture(base):
    root=base/'source'; (root/'agentrivet').mkdir(parents=True)
    files=fixture_files()
    for name,text in files.items():(root/name).write_text(text)
    return root,[{'path':name,'sha256':pin(root/name)['sha256']} for name in sorted(files)]


def request(base,*,initial=1,repairs=1):
    root,files=original_fixture(base)
    _,cp=goal(base);c=contract(base)
    c['goal_binding']={'contract':cp,'assignment_id':'summary-child'}
    c['budget'].update(calls=20,output_tokens=20*2048,wall_seconds=1800)
    campaign=base/'campaign';research_cycle.create(campaign,c,base_dir=base, evaluation_harness=True)
    paper=base/'paper.txt';paper.write_text('Complete own synthetic paper text; no physical benchmark.\n')
    calls=1+3*(initial+repairs)
    return {'schema_version':1,'campaign':str(campaign),'upstream':{'root':str(root),'files':files},'paper':pin(paper),
        'hepdata':{'context':None,'assets':[]},'metadata':{'arxiv_id':'synthetic','inspire_id':None,'collaboration':None,'preprint_year':None},
        'provider':{'model':'fixture-model','reasoning_effort':'high','max_calls':calls,'max_output_tokens':2048,'max_wall_seconds':700},
        'initial_rounds':initial,'max_native_repairs':repairs,'review_policy':review_wrapper(),'approval_mode':'scripted_yes'}


def host(monkeypatch,queue,seen):
    import platform
    monkeypatch.setattr(platform,'platform',lambda:'inert metadata; no subprocess')
    result=agent_host.AgentHost(endpoint='http://127.0.0.1:1/v1/responses')
    def response(data,parameters,request,control,**kwargs):
        seen.append(json.loads(data)); value=queue.pop(0)
        if isinstance(value,Exception):raise value
        return result._result(value,parameters,request,observed_model='fixture-model',response_id='own-inert-response',usage={'input_tokens':1,'output_tokens':1,'reasoning_tokens':None})
    monkeypatch.setattr(result,'_responses',response)
    return result


def triplet(code=CODE.decode(),approved=True):
    review=deepcopy(REVIEW);review['approved']=approved
    return [{'text':code},review,deepcopy(PHYSICS)]
