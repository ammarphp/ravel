"""Root-admitted pure fake-reader lifecycle fixture, never a Linux/site proof.

Only the external ROOT-reader call is substituted in the child. Plan, approval,
worker registration, selected attempt, supervisor, outputs and ending readers
remain the actual ordinary APIs. Author has not executed these controls.
"""

from method_decision_fixture import admit_method
from copy import deepcopy
import json
from pathlib import Path
import sys
from ravel.workflow import science,research_cycle as cycle
from ravel.workflow.state_io import atomic_json
from ravel.physics import root_stream as s
from root_stream_fixture import population, event_population, put, pin
from site_ordinary_fixture import policy


WRAPPER = r'''import sys,json
from pathlib import Path
wrapper=Path(__file__).absolute();source=Path(sys.argv[1]);args=sys.argv[2:]
sys.path.insert(0,str(source))
from ravel.workflow import science
def command(module,*args,python=None):
    if module!='ravel.physics.science_worker':raise ValueError('synthetic worker scope')
    return [sys.executable,'-B',str(wrapper),str(source),*(str(x) for x in args)]
science.module_command=command
from ravel.physics import reinterpret_db,root_stream_worker as w,root_stream as s
def synthetic_reader(argv,output,limits):
    raw=w.read_pinned(argv[-2],argv[-1],64*1024**2);req=json.loads(raw)
    events=json.loads((wrapper.parent/'events.json').read_bytes())
    import awkward as ak
    import numpy as np
    class Opened:
        def close(self):pass
    class Tree:
        def __init__(self,member):
            self.member=member;self.num_entries=member['entries']
        def arrays(self,names,entry_start,entry_stop,library):
            identity=self.member['id'].removesuffix('_file')
            rows=events[identity][entry_start:entry_stop]
            values={'w':[x[0] for x in rows],'sf':[x[1] for x in rows],
                'variation':[x[2] for x in rows],
                'x':[x[3][0][0] if x[3] else 0. for x in rows]}
            return ak.Array({name:np.asarray(values[name],dtype=np.float64) for name in names})
    result=w.stream(req['dataset'],req['analysis'],req['config'],req['bundle_directory'],
        reader=lambda handle,member:(Opened(),Tree(member)))
    s.write_new(Path(output)/'native-result.json',result)
    return {'kind':'synthetic_pure_reader_ordinary_control','external_native_calls':0,
        'site_runtime_validated':False,'physics_validated':False}
reinterpret_db.execute_native=synthetic_reader
from ravel.physics.science_worker import main
raise SystemExit(main(args))
'''


def prepare_fixture(root,monkeypatch,*,fail_reader=False,seconds=40,wall_seconds=None):
    """``seconds`` is the source plan's wall ceiling, which bounds the partition, merge and master
    budgets; ``wall_seconds`` replaces the owning campaign's wall budget, counted from its first dispatch."""
    root.mkdir();owner=contract(root)
    if wall_seconds is not None:owner['budget']['wall_seconds']=wall_seconds
    cycle.create(root/'cycle',owner,base_dir=root, evaluation_harness=True)
    ds,a,cfg,task,proof=population(root)
    events=event_population();events['signal'][1]=(1,.5,1,[[.5]]);rt=root/'runtime';wrapper=rt/'ordinary_reader.py'
    wrapper.write_text(WRAPPER.replace("    raw=w.read_pinned","    raise ValueError('admitted synthetic reader failure')\n    raw=w.read_pinned") if fail_reader else WRAPPER);put(rt,'events.json',events)
    # Each admitted row's original multifill is preserved. Blinding runs first
    # in worker.stream; the fixture kernel receives only admitted entries.
    fills={sample:[row[3] for row in rows] for sample,rows in events.items()}
    kernel=('FILLS='+repr(fills)+'\ndef analyze(table,entries,sample):\n'
        '    return [{"source_entry":int(e),"fills":{"regions":FILLS[sample["id"]][int(e)]}} for e in entries]\n').encode()
    cfg['bundle']['files']['kernel.py']=put(root,'kernel.py',kernel)
    assets={p.name:{k:pin(p)[k] for k in ('sha256','size')} for p in rt.iterdir() if p.is_file()}
    cfg['runtime']['trees'][0]['manifest']=put(root,'runtime.json',{'schema_version':1,'files':assets})
    cfg['limits']['max_seconds']=seconds;cfg['limits']['max_ram_mib']=512
    task={'config':put(root,'config.json',cfg)}
    review=policy();review.update(max_redos=0,allowed_stages=['science'],allowed_changed_paths=[],
        claim_scopes={s.SCOPE:{'checks':['integrity'],'actions':['delivery']}})
    spec={'schema_version':2,'mode':'root-stream','source':'Root-admitted pure synthetic partition lifecycle',
        'assumptions':['Fake reader only; no ROOT/site runtime or physics acceptance'],
        'max_seconds':seconds,'max_attempts':1,'approval_mode':'scripted_yes','task':task,
        'review_policy':{'schema_version':1,'policy':review,
            'correction_contract':{'task_fields':[],'input_slots':[]}}}
    source=Path(s.__file__).parents[2]
    def command(module,*args,python=None):
        assert module=='ravel.physics.science_worker'
        return [sys.executable,'-B',str(wrapper),str(source),*(str(x) for x in args)]
    monkeypatch.setattr(science,'module_command',command)
    return ds,a,cfg,put(root,'spec.json',spec),proof


def ordinary(specification,rd):
    science.plan(rd,specification['path']); admit_method(rd)
    assert science.verify_plan(rd,approved=False)['schema_version']==2
    science.approve(rd,'Root-admitted pure software fixture; not expert physics review',scripted=True)
    science.run(rd)
    receipt=s.ordinary_delivery(rd)
    assert receipt['result']['status']=='passed'
    assert science.execution.load_execution(rd)['stages']['science']['status']=='succeeded'
    return receipt


# Exact finite source extraction from C37 test_site_workflow.law; provenance in manifest.
def law(proof,expected=False):
    bins=[{'id':'Signal','role':'signal_region','observed':None,'observation_id':'signal','source':'law'},
          {'id':'Control','role':'control_region','observed':None if expected else 0,'observation_id':'control','source':'law'}] if expected else [{'id':'Control','role':'control_region','observed':0,'observation_id':'control','source':'law'}]
    n=len(bins)
    d={'schema_version':1,'model_id':'Expected' if expected else 'Background','question':'Synthetic complete source-defined background and sensitivity design',
       'sources':[{'id':'law','path':proof['path'],'sha256':proof['sha256']}],
       'parameters':[{'name':'mu','role':'poi','initial':'1','bounds':['0','10'],'fixed':False,'meaning':'supplied strength','source':'law'},
                     {'name':'beta','role':'rate','initial':'1','bounds':['0','10'],'fixed':False,'meaning':'supplied background normalization','source':'law'}],
       'bins':bins,'terms':[{'id':'B','basis':'background','coefficients':['0']*n,'powers':{'beta':1},'log_response':[[] for _ in bins],'source':'law'},
                           {'id':'S','basis':'bsm','coefficients':['0']*n,'powers':{'mu':1},'log_response':[[] for _ in bins],'source':'law'}],
       'auxiliary':{'kind':'supplied_gaussian_factor','names':[],'observed':[],'factor':[],'eta_bounds':[],'source':'law'},
       'partition':{'kind':'declared_disjoint_poisson_counts','source':'law','statement':'Synthetic caller-independent physical event assumption'},
       'prediction':{'units':'expected_events','energy':'13 TeV supplied fixture','luminosity':'1 fb^-1 supplied fixture','basis':'supplied nonnegative background and signal','scale':'supplied','domain_statement':'caller conditional domain','source':'law'},
       'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Full signed MC covariance retained; no nuisance law inferred','source':'law'},
       'assumptions':[{'id':'Conditional','statement':'Synthetic conditional source law, no physics qualification','source':'law','status':'assumed'}]}
    if expected:d['expected_data']={'kind':'regional-background-asimov/v1','conditioning':'supplied_nominal','point':{'mu':'0','beta':'1'},'source':'law','statement':'supplied expected sensitivity state, no observed SR','fit':None}
    return d


# Exact three-function source extraction from C37 test_research_cycle; no imports of that suite.

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if type(value) is str: path.write_text(value)
    else: atomic_json(path, value)
    return cycle._pin(path)

def source_context(base):
    source = write(base / "math.py", "def group_variance(weights):\n    return sum(weights)**2\n")
    return {"schema_version": 1, "task_id": "signed-group-question", "task": "Deliver the paired two-record conditional variance and preserve all negative results.",
        "source_capsules": [], "api_documents": [{"id": "math", "pin": {k: source[k] for k in ("path", "sha256")},
            "language": "python", "role": "api", "version": "Explicit own synthetic math control, not native", "dependencies": []}],
        "queries": [{"id": "group-math", "symbol": "group_variance", "mode": "definition", "documents": ["math"], "required": True}],
        "requested_quantities": [{"id": "conditional-variance", "artifact": "measurement", "pointer": "/quantities/covariance",
            "check": {"kind": "exact", "value": [[1.0]]}, "meaning": "Two supplied signed contributions 2 and -1 in one explicit group; no physical uncertainty qualification."}],
        "compatibility_groups": [{"id": "current-candidate", "artifacts": ["measurement"], "carryover": False,
            "basis": "Every new candidate must supply its own complete two-record result."}],
        "max_source_bytes": 128000, "max_context_bytes": 16000, "max_steps": 6}

def contract(base):
    return {"schema_version": 1, "id": "supplied-group-investigation", "question": "Can pairing signed supplied subevents change conditional variance while retaining the sum?",
        "scope": "Synthetic engineering loop; neither independent model reasoning nor physics efficacy.",
        "context_request": write(base / "context-request.json", source_context(base)),
        "premises": [{"id": "pairing", "statement": "The actual initial record population has separate groups.", "basis": []}],
        "budget": {"calls": 20, "output_tokens": 0, "wall_seconds": 600, "native_attempts": 6},
        "max_experiments": 6, "exploration_every": 2, "required_experiments": ["paired"]}
