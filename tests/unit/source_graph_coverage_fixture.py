"""Explicit inert stand-ins extracted from prior portable controls; not ROOT/physics evidence."""
import ast,hashlib,itertools,json,math,re,sys
from pathlib import Path
from fractions import Fraction as F
from copy import deepcopy
from types import ModuleType,SimpleNamespace
import pytest
from ravel.physics import statistical_construction as c,native_statistical_construction as n,native_likelihood as native
from ravel.workflow import agent_graph
def law_fixture(tmp_path, correlated=False):
    src = tmp_path / 'supplied.txt'; src.write_text('Artificial source for arithmetic controls, not experimental data.\n')
    k = 2 if correlated else 0
    par = lambda n, role, v, b, fixed=False: {'name': n, 'role': role, 'initial': v, 'bounds': b, 'fixed': fixed, 'meaning': n, 'source': 's'}
    d = {'schema_version': 1, 'model_id': 'regional', 'question': 'Retain full A/B/C/D signal and transfer inference.',
         'sources': [{'id': 's', 'path': str(src), 'sha256': hashlib.sha256(src.read_bytes()).hexdigest()}],
         'parameters': [par('c', 'poi', '0', ['-2', '2']), par('beta', 'rate', '5', ['0','20']),
                        par('u','rate','2',['0','5']), par('v','rate','3',['0','5']), par('kappa','rate','1',['0','2'],True)],
         'bins': [{'id': n, 'role': 'signal_region' if n=='A' else 'control_region', 'observed': obs, 'observation_id': 'events/'+n, 'source':'s'} for n,obs in zip('ABCD',[30,10,15,5])],
         'terms': c.abcd_terms(list('ABCD'), dict(zip('ABCD','ABCD')), beta='beta', x='u', y='v', closure='kappa',source='s',auxiliary_count=k),
         'auxiliary': {'kind':'supplied_gaussian_factor','names':['shape','transfer'] if k else [], 'observed':['0','0'] if k else [],
                       'factor':[['1','0'],['3/5','4/5']] if k else [],'eta_bounds':[['-3','3'],['-4','4']] if k else [],'source':'s'},
         'partition':{'kind':'declared_disjoint_poisson_counts','source':'s','statement':'Assumed artificial disjoint A/B/C/D observations.'},
         'prediction':{'units':'expected_events','energy':'artificial','luminosity':'artificial','basis':'supplied signed c convention','scale':'same-scale artificial','domain_statement':'Box and positive full means; native domain unqualified.','source':'s'},
         'template_statistics':{'kind':'conditional_on_supplied_coefficients','statement':'Artificial exact inputs; no MC auxiliaries.','source':'s'},
         'assumptions':[{'id':'conditional','statement':'This artificial law is supplied, not a physics claim.','source':'s','status':'assumed'}]}
    for ident,power,coefs in [('linear',1,['-4','1','-2','0']),('square',2,['2','1','3','1'])]:
        d['terms'].append({'id':ident,'basis':'interference' if power==1 else 'bsm','coefficients':coefs,'powers':{'c':power},'log_response':[['0']*k for _ in 'ABCD'],'source':'s'})
    return d

def state(d, point=None):
    point=point or c.initial_point(d)
    s={p['name']:{'value':float(F(point[p['name']])),'minimum':float(F(p['bounds'][0])),'maximum':float(F(p['bounds'][1])),'constant':p['fixed']} for p in d['parameters']}
    for i,b in enumerate(d['auxiliary']['eta_bounds']):
        n='ravel_aux_'+str(i);s[n]={'value':float(F(point[n])),'minimum':float(F(b[0])),'maximum':float(F(b[1])),'constant':False}
    return s

def count_product_fixture(d, witnesses):
    """Supplied graph/data observations, not a ROOT result or runtime qualification.

    CountingModelBuilder represents all disjoint-bin counts in one data row.
    Its model_s multiplies their Poissons by the single nuisance factor product.
    """
    bins=d['bins']; count_names=['pdf_bin'+b['id'] for b in bins]
    aux_names=['ravel_aux_'+str(i)+'_Pdf' for i in range(len(d['auxiliary']['names']))]
    leaves=[]; rows=[]
    def proxy(roles,servers):
        codes={roles['x']:1,roles['mean']:2}
        if 'sigma' in roles:codes[roles['sigma']]=0
        return {'method':'ROOT6.22/getAnalyticalIntegral-name-match/v1','roles':roles,
                'queries':[{'server':n,'code':codes[n],'selected':[n] if codes[n] else []} for n in servers]}
    # Independent ABCD means at the fixture's c=eta=0: beta=5,u=2,v=3,kappa=1.
    initial_means=[30.,10.,15.,5.]
    for i,b in enumerate(bins):
        ident=b['id'];mean='n_exp_bin'+ident;full=mean+'_proc_ravel_full';dummy=mean+'_proc_ravel_dummy';fn='ravel_mean_'+str(i)
        pdf={'name':'pdf_bin'+ident,'class':'RooPoisson','servers':['n_obs_bin'+ident,mean]}
        pdf['proxy_identity']=proxy({'x':'n_obs_bin'+ident,'mean':mean},pdf['servers'])
        leaves.append(pdf)
        rows.append({'channel':ident,'declared_role':b['role'],'pdf':pdf,'pdf_observables':['n_obs_bin'+ident],
            'mean':{'name':mean,'class':'RooAddition','servers':[full,dummy]},
            'full_process':{'name':full,'class':'ProcessNormalization','servers':[fn]},'count_function':fn,
            'dummy':{'name':dummy,'constant':True,'value':0.},'initial_total_mean':initial_means[i],
            'initial_count_function':initial_means[i]})
    widths={}
    for i,name in enumerate(aux_names):
        leaves.append({'name':name,'class':'SimpleGaussianConstraint','servers':['ravel_aux_'+str(i),'ravel_aux_'+str(i)+'_In','1']})
        leaves[-1]['proxy_identity']=proxy({'x':'ravel_aux_'+str(i),'mean':'ravel_aux_'+str(i)+'_In','sigma':'1'},leaves[-1]['servers'])
        widths[name]={'name':'1','constant':True,'value':1.}
    domains={n:{k:v[k] for k in ('minimum','maximum','constant')} for n,v in state(d).items()}
    q={'representation':'regional_count_product/v1','coordinate_domains':domains,
       'root':{'name':'model_s','class':'RooProdPdf','servers':['modelObs_s','nuisancePdf']},
       'products':[{'name':'model_s','class':'RooProdPdf','factors':['modelObs_s','nuisancePdf']},
                   {'name':'modelObs_s','class':'RooProdPdf','factors':count_names},
                   {'name':'nuisancePdf','class':'RooProdPdf','factors':aux_names}],
       'leaves':leaves,'rows':rows,'constant_width_reads':len(aux_names),'auxiliary_widths':widths,
       'extra_initial_mean_evaluations':2*len(bins),'constant_dummy_reads':len(bins),
       'semantic_proxy_queries':3*len(aux_names)+2*len(bins)}
    globals_=['ravel_aux_'+str(i)+'_In' for i in range(len(aux_names))]
    return {'workspace':{'pois':['c'],'channels':[],'data_entries':1,'observables':['n_obs_bin'+b['id'] for b in bins],
             'poi_domain':[-2.,2.],'nuisances':['beta','u','v','ravel_aux_0','ravel_aux_1'],'global_observables':globals_},
            'fixed_witnesses':witnesses,'construction_linkage':q,
            'construction_global_ranges':{n:{'has_min':False,'has_max':False} for n in globals_},
            'construction_observations':{'counts':{b['id']:b['observed'] for b in bins},'dataset_weight':1.,
                'auxiliary':{n:{'value':0.,'constant':True} for n in globals_}}}
def pin(p):
    return {'path':str(p.resolve()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def fixture(tmp_path, monkeypatch, *, population=False):
    law = law_fixture(tmp_path, True)
    source = tmp_path/'original'; source.mkdir()
    code = b'class OriginalShape {};\n// original observable and parameter mapping\n// original full nominal/up/down morph mapping\n'
    (source/'Original.cc').write_bytes(code)
    capsule_files = [{'path':'Original.cc','sha256':pin(source/'Original.cc')['sha256'],'role':'compile'}]
    nodes = []
    for name,values in [('nominal',['2','3']),('up',['4','6']),('down',['1','3/2'])]:
        t = {'edges':['1','2','4'],'values':values,'semantics':'absolute_bin_integrals_piecewise_constant'}
        path=name+'.json'; (source/path).write_bytes(n.encoded(t))
        capsule_files.append({'path':path,'sha256':pin(source/path)['sha256'],'role':'data'})
        nodes.append({'name':name,'kind':'template','class':'RooHistFunc','depends_on':['massObs'],'members':['morph_source'],
                      'template':{'source_path':path,'observable':'massObs',**t}})
    nodes += [{'name':'morph','kind':'factory','class':'RooAddition','depends_on':['nominal','up','down'],'members':['morph_source'],
               'factory':'sum::morph(nominal,up,down)'},
              {'name':'interference','kind':'factory','class':'RooFormulaVar','depends_on':['massObs','slope'],'members':['class_source'],
               'factory':'expr::interference("@0*@1",massObs,slope)'}]
    members = [{'id':name,'path':'Original.cc','first_line':i,'last_line':i,'sha256':hashlib.sha256(code.splitlines(keepends=True)[i-1]).hexdigest(),'depends_on':deps}
               for i,name,deps in [(1,'class_source',['coordinate_source']),(2,'coordinate_source',[]),(3,'morph_source',['class_source'])]]
    tool=tmp_path/'tool';tool.write_text('#!/bin/sh\nexit 99\n');tool.chmod(0o755)
    lib=tmp_path/'libHiggsAnalysisCombinedLimit.so';lib.write_bytes(b'inert library, never loaded')
    module=tmp_path/'PhysicsModel.py';module.write_text('# inert module, never imported\n')
    version=tmp_path/'combine.cc';version.write_text('std::string combineTagString = "v9.2.1";\nif(datacard == "") { cerr << "Missing datacard file" << endl; return 1002; }\nif (seed == -1) {}\ncombiner.applyOptions(vm);\n')
    runtime={'tools':{k:pin(tool) for k in ('combine','text2workspace','python')},'artifacts':[pin(lib),pin(module)],'environment':{'PATH':'/usr/bin:/bin'},
             'expected':{'combine_version':'9.2.1','root_version':'6.22/00','cmssw_version':None,'architecture':'x86_64','custom_classes':['RooParametricHist']},
             'transport':{'kind':'local'},'version_proof':{'kind':'missing_datacard_diagnostic','source':pin(version),'expected_returncode':234}}
    fit={'method':'MultiDimFit','data':'observed','poi':'c','domain':['-2','2'],'mass':120,'seed':12345,'points':None,'minimizer':None,'fixed_witness_points':['0','1'],'reference_quantiles':None,
         'saved_fit':{'algorithm':'none','required_object':'multidimfit.ravel.root:fit_mdf','maximum_edm':.001}}
    axes={'mass':['120','240'] if population else ['120'],'width':['narrow','wide'] if population else ['declared_width'],
          'hypothesis':['signal','interference'] if population else ['source_hypothesis'],'candidate':['first','second'] if population else ['source_candidate']}
    cell={'id':'cell','coordinates':{},'law':law,'parameters':[{'name':'slope','initial':'0','bounds':['-2','2'],'fixed':False,'unit':'dimensionless','member':'coordinate_source'}],
          'observables':[{'name':'massObs','bounds':['1','4'],'unit':'GeV','member':'coordinate_source'}], 'nodes':nodes,
          'integration':{'eps_abs':'1e-8','eps_rel':'1e-8','max_steps':12,'policy':'ROOT6.22-RooIntegrator1D-original-default-zero-policy'}, 'fit':fit}
    common={'observable':'massObs','bin_windows':[['1','2'],['2','4'],['1','3'],['3','4']], 'log_response':[['1','-1'],['0','0'],['1/2','0'],['0','1']], 'meaning':'Complete supplied SR/CR leakage and shared auxiliary response'}
    cell['components']=[{**deepcopy(common),'id':'resonance','node':'morph','normalization':'full_domain','measure':'density','role':'signal','coefficients':['6','2','3','1'],'powers':{'c':2}},
                        {**deepcopy(common),'id':'signed','node':'interference','normalization':'absolute_integral','measure':'signed_density','role':'interference','coefficients':['-1','2','-3','1'],'powers':{'c':1}}]
    cells=[]
    for i,values in enumerate(itertools.product(*(axes[a] for a in n.AXES))):
        row=deepcopy(cell);row['id']='cell'+str(i);row['coordinates']=dict(zip(n.AXES,values));cells.append(row)
    review=tmp_path/'existing-review';review.mkdir();(review/'state.lock').write_bytes(b'');(review/'state.json').write_bytes(b'inert existing review fixture\n')
    d={'schema_version':1,'kind':n.KIND,'question':'Construct the complete original native likelihood without a prebuilt card.','scope':'All original cells and full four-region counting/auxiliary law',
       'population':axes,'cells':cells,'source_capsule':{'schema_version':1,'kind':'analysis-source-capsule','framework':'cpp','routine':'OriginalShape',
       'source':{'repository':'supplied','revision':None,'description':'Inert source fixture, not actual independent review'},'root':str(source),'files':capsule_files,
       'layout':{'include_dirs':['.'],'asset_dirs':['.']},'dependencies':[{'name':'original','kind':'source','status':'resolved','files':['Original.cc'],'reason':'Explicit complete original member mapping'}],
       'dependency_review':{'complete':True,'description':'Synthetic gate control only'},'submodules':[]},'members':members,'runtime':runtime,'max_seconds':30,
       'assumptions':['Synthetic source/buildout control; no ROOT/native or scientific qualification.'],'review':{}}
    subject=tmp_path/'subject.json';subject.write_bytes(n.subject(d))
    d['review']={'root':str(review),'files':[{'path':p.name,'sha256':pin(p)['sha256']} for p in sorted(review.iterdir())], 'subject':pin(subject),
                 'critic':{'node':'critic','packet_sha256':'1'*64},'verifier':{'node':'verifier','packet_sha256':'2'*64}}
    seen=[]
    def receipt(root,node,**kwargs):
        seen.append((root,node,kwargs))
        assert kwargs=={'expected_subject_sha256':d['review']['subject']['sha256'],'expected_packet_sha256':d['review'][node]['packet_sha256'],'require_exact_subject':True}
        return {'role':node,'public_value':{'kind':'native-source-graph-review/v1','decision':'source_clear','subject_sha256':d['review']['subject']['sha256'],
                'members':[r['id'] for r in members],'unresolved':[],'physics_validated':False,'numerical_equivalence_qualified':False}}
    monkeypatch.setattr(agent_graph,'model_receipt',receipt)
    return d,seen

def structural_fixture(tmp_path,monkeypatch):
    d,_=fixture(tmp_path,monkeypatch);r=n.response(d,'cell0');cell=d['cells'][0]
    witnesses=[]
    for point in cell['fit']['fixed_witness_points']:
        values=state(cell['law']);values['c']['value']=float(F(point))
        values['slope']={'value':0.,'minimum':-2.,'maximum':2.,'constant':False}
        witnesses.append({'point':point,'raw_nll_at_source_nuisance_values':123.,'construction_state':values,
                          'scales':{name:37.+i for i,name in enumerate(r['functions'])}})
    probe=count_product_fixture(cell['law'],witnesses)
    probe['workspace']['nuisances'].append('slope')
    probe['construction_linkage']['coordinate_domains']['slope']={'minimum':-2.,'maximum':2.,'constant':False}
    probe['source_graph_nodes']={node['name']:{'class':node['class'],'servers':sorted(node['depends_on'])} for node in cell['nodes']}
    probe['source_graph_observables']={'massObs':{'bounds':[1.,4.],'unit':'GeV','constant':True}}
    cfg={'fit':cell['fit'],'model':{'regions':[{'channel':b['id'],'role':b['role']} for b in cell['law']['bins']]}}
    return probe,cfg,r
class Var:
 def __init__(self,name,value,lo=-100,hi=100,fixed=False,unbounded=False):self.name=name;self.value=value;self.lo=lo;self.hi=hi;self.fixed=fixed;self.unbounded=unbounded
 def getVal(self):return self.value
 def setVal(self,v):self.value=float(v)
 def getMin(self):return self.lo
 def getMax(self):return self.hi
 def isConstant(self):return self.fixed
 def setConstant(self,v):self.fixed=v
 def hasMin(self):return not self.unbounded
 def hasMax(self):return not self.unbounded
 def GetName(self):return self.name
 def getError(self):return max(0.,getattr(self,'error',.1))
 def setError(self,x):self.error=x
 def hasError(self):return getattr(self,'error',.1)>=0
 def removeError(self):self.error=-1.
 def hasAsymError(self):return getattr(self,'asym',None) is not None
 def getAsymErrorLo(self):return self.asym[0] if self.hasAsymError() else 0.
 def getAsymErrorHi(self):return self.asym[1] if self.hasAsymError() else 0.
 def setAsymError(self,a,b):self.asym=(a,b)
 def removeAsymError(self):self.asym=None

class Collection(list):
 def find(self,name):return next((v for v in self if v.name==name),None)
 def getSize(self):return len(self)

class Data:
 def __init__(self,w,bins):self.w=w;self.bins=bins;self.rows=[[w.var('n_obs_bin'+b['id']).getVal() for b in bins]]
 def numEntries(self):return len(self.rows)
 def weight(self):return 1.
 def get(self,i):return Collection([Var('n_obs_bin'+b['id'],v) for b,v in zip(self.bins,self.rows[i])])
 def reset(self):self.rows=[]
 def add(self,obs):self.rows.append([v.getVal() for v in obs])
def policy():
    return {"schema_version": 1,
        "actors": {"proposer": "worker", "executor": "worker", "physics_decider": "physicist", "skeptical_verifier": "skeptic", "physics_critic": "critic"},
        "max_redos": 2, "allowed_changed_paths": ["inputs/settings.cfg"], "allowed_stages": ["detector"],
        "required_checks": [{"id": "integrity", "kind": "integrity"}, {"id": "agreement", "kind": "scientific"}],
        "claim_scopes": {"diagnostic": {"checks": ["integrity"], "actions": ["delivery"]},
            "reproduction": {"checks": ["integrity", "agreement"], "actions": ["bulk", "delivery", "reuse"]}}}
