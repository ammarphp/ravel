"""Prospective bounded analytic-source qualification and full-nuisance fits.

New fixed-mark experiments are explicit supplied models, not native MC claims.
Execution belongs to the approved scientific supervisor; this module has no CLI.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import pyhf
from scipy.stats import multinomial, norm, poisson
from scipy.special import gammaln, xlogy

from ravel.physics import finite_mc_model as fm
from ravel.physics.mc_auxiliary import MCAuxiliaryBlock, compact, _read, MAX_TOTAL_BYTES
from ravel.physics.joint_analytic import AnalyticPublishedJoint, AnalyticJointProfiler
from ravel.physics.joint_profile import WorkBudget
from ravel.physics.published_background import BackgroundAuxBlock, inspect_workspace
from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
from ravel.physics.quantities import _keys, _number, _text

MAX_RESULT_BYTES=32*1024**2


def validate(task):
    _keys(task,("input",),label="full-source qualification task")
    _text(task["input"],"input path")


def _pin(row,base,captured):
    _keys(row,("path","sha256"),label="qualification source pin")
    _text(row["path"],"source path")
    if not isinstance(row["sha256"],str) or len(row["sha256"])!=64:raise ValueError("SHA256 source pin required")
    path=fm._regular(row["path"],base);raw=_read(path)
    if hashlib.sha256(raw).hexdigest()!=row["sha256"]:raise ValueError("qualification source pin changed")
    if str(path) in captured and captured[str(path)]!=raw:raise ValueError("capture source changed")
    captured[str(path)]=raw
    if sum(map(len,captured.values()))>MAX_TOTAL_BYTES:raise ValueError("qualification aggregate bytes exceeded")
    return path,json.loads(raw)


def _law_only(document):
    return document.get("schema_version")==2 and document.get("execution_scope")=="law_only"


def _prepare(document):
    version=document.get("schema_version")
    if type(version) is not int or version not in (1,2):raise ValueError("unsupported qualification schema")
    common=("schema_version","model_id","measurement","background_source","cases","qualification","execution_seconds","outer_work_seconds","assumptions")
    _keys(document,common+(("execution_scope","qualification_mu_upper") if version==2 else ("fit",)),label="full-source qualification")
    law_only=_law_only(document)
    if version==2 and not law_only:raise ValueError("schema2 requires explicit law_only scope")
    if law_only:
        if not 0<_number(document["qualification_mu_upper"],"qualification mu upper")<=1000:raise ValueError("bounded qualification mu required")
        mu_upper=document["qualification_mu_upper"]
    for field in ("model_id","measurement"):_text(document[field],field)
    if type(document["execution_seconds"]) is not int or not 1<=document["execution_seconds"]<=300:raise ValueError("at most300second supervisor ceiling required")
    if not 0<_number(document["outer_work_seconds"],"outer work seconds")<=document["execution_seconds"]-1:raise ValueError("explicit outer work deadline below supervisor ceiling required")
    q=document["qualification"]
    _keys(q,("steps","mean_atol","mean_rtol","nll_atol","gradient_atol","gradient_rtol","wall_seconds","density_wrapper_calls","pyhf_main_calls","source_auxiliary_factor_calls","MC_density_calls"),label="qualification budget")
    if not isinstance(q["steps"],list) or len(q["steps"])!=2 or not 0<_number(q["steps"][1],"small step")<_number(q["steps"][0],"step")<=1e-3:raise ValueError("two distinct small derivative steps required")
    for field in ("mean_atol","mean_rtol","nll_atol","gradient_atol","gradient_rtol"):
        if not 0<_number(q[field],field)<=1e-2:raise ValueError("explicit bounded numerical tolerances required")
    if not 0<_number(q["wall_seconds"],"qualification wall seconds")<=60:raise ValueError("qualification ceiling60seconds")
    for field in ("density_wrapper_calls","pyhf_main_calls","source_auxiliary_factor_calls","MC_density_calls"):
        if type(q[field]) is not int or not 1<=q[field]<=200000:raise ValueError("bounded qualification call count required")
    if not law_only:
        fit=document["fit"]
        _keys(fit,("mu_domain","fixed_strength","budget_per_fit","endpoint_verification"),label="fit protocol")
        _keys(fit["mu_domain"],("initial","upper"),label="numerical mu search")
        if not 0<_number(fit["mu_domain"]["initial"],"mu initial")<_number(fit["mu_domain"]["upper"],"mu upper")<=1000:raise ValueError("finite mu search required")
        if not 0<=_number(fit["fixed_strength"],"fixed strength")<=fit["mu_domain"]["upper"]:raise ValueError("fixed strength outside search")
        WorkBudget(fit["budget_per_fit"])
        if fit["budget_per_fit"]["wall_seconds"]>25:raise ValueError("per-fit wall ceiling25seconds")
        endpoint=fit["endpoint_verification"]
        _keys(endpoint,("wall_seconds","density_wrapper_calls","pyhf_main_calls","source_auxiliary_factor_calls","MC_density_calls"),label="per-fit endpoint verification")
        if not 0<_number(endpoint["wall_seconds"],"endpoint wall")<=5:raise ValueError("endpoint wall ceiling5seconds")
        for field in ("density_wrapper_calls","pyhf_main_calls","source_auxiliary_factor_calls","MC_density_calls"):
            if type(endpoint[field]) is not int or not 1<=endpoint[field]<=10000:raise ValueError("bounded endpoint calls required")
        mu_upper=fit["mu_domain"]["upper"]
    cases=document["cases"]
    if not isinstance(cases,list) or not 1<=len(cases)<=2:raise ValueError("one or two source cases required")
    for case in cases:
        _keys(case,("id","workspace","mc_model","signal_samples","source_bin_map","source_bound_semantics","initial_point","interior_point","expected_source_coordinates","expected_free_coordinates"),label="qualification case")
        _text(case["id"],"case id")
        for field in ("expected_source_coordinates","expected_free_coordinates"):
            if type(case[field]) is not int or not 1<=case[field]<=256:raise ValueError("explicit bounded coordinate count required")
        for field in ("initial_point","interior_point"):
            point=case[field];_keys(point,("mu","source","latent"),label="qualification point")
            if not 0<=_number(point["mu"],"qualification mu")<=mu_upper:raise ValueError("qualification mu outside search")
            if not isinstance(point["source"],dict) or not isinstance(point["latent"],dict):raise ValueError("complete literal source/latent vectors required")
            for value in list(point["source"].values())+list(point["latent"].values()):_number(value,"literal coordinate")
    if len({c["id"] for c in cases})!=len(cases):raise ValueError("unique case identities required")
    if not isinstance(document["assumptions"],list) or len(document["assumptions"])<3:raise ValueError("explicit scientific limitations required")
    for statement in document["assumptions"]:_text(statement,"assumption")
    return deepcopy(document)


def _capture(task,base_dir):
    validate(task);path=fm._regular(task["input"],base_dir);raw=_read(path)
    document=_prepare(json.loads(raw));captured={str(path):raw}
    _,background=_pin(document["background_source"],path.parent,captured)
    cases=[]
    for row in document["cases"]:
        _,workspace=_pin(row["workspace"],path.parent,captured)
        mcpath,_=_pin(row["mc_model"],path.parent,captured)
        mc=MCAuxiliaryBlock({"input":str(mcpath)})
        for p,data in mc._captured.items():
            if p in captured and captured[p]!=data:raise ValueError("MC capture source changed")
            captured[p]=data
        if sum(map(len,captured.values()))>MAX_TOTAL_BYTES:raise ValueError("qualification aggregate bytes exceeded")
        design=mc.document()["mc_design"]
        if design["kind"]!="fixed_n_categories" or design["total_groups"]>300:raise ValueError("restricted complete fixed-N study up toN300 required")
        if compact(inspect_workspace(workspace,row["signal_samples"])["background_projection"])!=compact(background):raise ValueError("exact supplied BkgOnly projection required")
        cases.append((row,workspace,mc))
    for p,data in captured.items():
        if _read(Path(p))!=data:raise ValueError("qualification input changed during capture")
    return document,captured,background,cases


def inputs(task,base_dir):
    _,captured,_,_=_capture(task,base_dir)
    return [Path(p) for p in captured]


def _bounds(document):
    if _law_only(document):
        return {"execution_scope":"law_only","execution_seconds":document["execution_seconds"],"outer_work_seconds":document["outer_work_seconds"],
                "qualification_wall_seconds":document["qualification"]["wall_seconds"],"processes":1,"requested_BLAS_threads":1,"native_thread_ceiling_measured":False,
                "maximum_fit_calls":0,"maximum_optimizer_attempts":0,"maximum_optimizer_objective_calls":0,"maximum_total_analytic_gradient_calls":2*len(document["cases"]),"maximum_optimizer_analytic_gradient_calls":0,
                "maximum_total_seed_LP_calls":0,"maximum_total_stationarity_LP_calls":0,"maximum_total_optimizer_iterations":0,
                "maximum_analytic_qualification_evaluations":2*len(document["cases"]),"maximum_source_model_compilations":4*len(document["cases"]),
                "qualification_call_ceilings":deepcopy(document["qualification"]),"endpoint_call_ceilings_per_fit":None,
                "maximum_total_endpoint_calls":{key:0 for key in ("density_wrapper_calls","pyhf_main_calls","source_auxiliary_factor_calls","MC_density_calls")},
                "maximum_endpoint_wall_seconds_total":0,"case_free_coordinate_counts":{c["id"]:c["expected_free_coordinates"] for c in document["cases"]},
                "maximum_input_bytes":MAX_TOTAL_BYTES,"maximum_result_and_journal_bytes_each":MAX_RESULT_BYTES,
                "enforcement":"Explicit law-only branch; no profiler construction, optimizer, seed LP, stationarity LP or endpoint fit verification. Supervisor owns native-thread and memory monitoring."}
    fits=4*len(document["cases"]);budget=document["fit"]["budget_per_fit"]
    return {"execution_seconds":document["execution_seconds"],"outer_work_seconds":document["outer_work_seconds"],"qualification_wall_seconds":document["qualification"]["wall_seconds"],
            "processes":1,"requested_BLAS_threads":1,"native_thread_ceiling_measured":False,"maximum_fit_calls":fits,"maximum_optimizer_attempts":3*fits,
            "maximum_analytic_qualification_evaluations":2*len(document['cases']),"maximum_source_model_compilations":4*len(document['cases']),
            "maximum_total_objective_calls":fits*budget["objective_calls"],"maximum_total_analytic_gradient_calls":fits*budget["gradient_calls"],
            "maximum_total_seed_LP_calls":fits*budget["feasibility_lp_calls"],"maximum_total_stationarity_LP_calls":fits*budget["stationarity_lp_calls"],
            "maximum_total_optimizer_iterations":3*fits*budget["maxiter"],"qualification_call_ceilings":deepcopy(document["qualification"]),"endpoint_call_ceilings_per_fit":deepcopy(document["fit"]["endpoint_verification"]),
            "maximum_total_endpoint_calls":{key:fits*value for key,value in document['fit']['endpoint_verification'].items() if key!='wall_seconds'},
            "maximum_endpoint_wall_seconds_total":fits*document['fit']['endpoint_verification']['wall_seconds'],
            "case_free_coordinate_counts":{c["id"]:c["expected_free_coordinates"] for c in document["cases"]},"maximum_input_bytes":MAX_TOTAL_BYTES,"maximum_result_and_journal_bytes_each":MAX_RESULT_BYTES,
            "enforcement":"One approved supervisor worker; per-call/per-fit hooks and iteration/count ceilings. Native-thread monitoring/interruption and peakmemory remain supervisor obligations."}


def resource_bounds(task,base_dir):return _bounds(_capture(task,base_dir)[0])
def execution_seconds(task,base_dir):return resource_bounds(task,base_dir)["execution_seconds"]


class Journal:
    """Write identities before work; timeout does not serialize solver memory."""
    def __init__(self,out):self.path=out/"qualification-progress.jsonl";self.previous=None;self.bytes=0;self.sequence=0
    def write(self,kind,identity,state,**fields):
        row={"sequence":self.sequence,"kind":kind,"identity":identity,"state":state,"previous_sha256":self.previous,**fields}
        raw=compact(row);self.bytes+=len(raw)+1
        if self.bytes>MAX_RESULT_BYTES:raise ValueError("qualification journal byte budget exceeded")
        with self.path.open("ab") as stream:stream.write(raw+b"\n");stream.flush()
        self.previous=hashlib.sha256(raw).hexdigest();self.sequence+=1


class QualificationBudget:
    def __init__(self,limits,outer_deadline):
        self.limits=deepcopy(limits);self.used={key:0 for key in ("density_wrapper_calls","pyhf_main_calls","source_auxiliary_factor_calls","MC_density_calls")}
        self.deadline=min(outer_deadline,time.monotonic()+limits["wall_seconds"])
    def check(self):
        if time.monotonic()>=self.deadline:raise TimeoutError("qualification wall hook exhausted")
    def charge(self,key,amount=1):
        self.check()
        if self.used[key]+amount>self.limits[key]:raise RuntimeError("qualification "+key+" ceiling exhausted")
        self.used[key]+=amount


def _compile(row,workspace,background_source,mc,measurement,model_id):
    bg=BackgroundAuxBlock(workspace,row["signal_samples"],measurement=measurement,policy="rebuild_background_mc_from_source",model_id=model_id+"/"+row["id"],background_source=background_source)
    if len(bg.contract()["active_parameter_names"])!=row["expected_source_coordinates"]:raise ValueError("compiled source coordinate census differs")
    for name in ("initial_point","interior_point"):
        p=row[name];bg._point(p["source"]);mc.nominal(p["latent"])
    if row["initial_point"]["source"]!=bg.initial_point() or row["initial_point"]["latent"]!={c["id"]:c["initial"] for c in mc.document()["classes"]}:raise ValueError("literal initial point differs from supplied source/MC initial values")
    if 1+sum(not d["fixed"] for d in bg.contract()["active_parameter_domains"].values())+len(mc.class_ids)-1!=row["expected_free_coordinates"]:raise ValueError("joined free dimension differs")
    joint=AnalyticPublishedJoint(bg,mc,source_workspace=workspace,signal_samples=row["signal_samples"],source_bin_map=row["source_bin_map"],model_id=model_id+"/analytic/"+row["id"],response_assumptions=["Explicit controlled fixed-mark/source diagonal response extension.","Retained source and complete new MC auxiliaries independent; no native generator law inferred."])
    return bg,joint


class IndependentSourceOracle:
    """Original pyhf means + separately compiled BkgOnly MC auxiliaries.

    Shares published inputs/runtime but no analytic graph or its derivatives.
    Signal subtraction uses both source passes at replaced gamma=1; background
    uses actual retained gamma. Gaussian/Poisson/MC densities use SciPy.
    """
    def __init__(self,workspace,background_source,row,mc,measurement,budget):
        self.original=pyhf.Workspace(workspace).model(measurement_name=measurement,modifier_settings=MODIFIER_SETTINGS)
        self.bg=pyhf.Workspace(background_source).model(measurement_name=measurement,poi_name=None,modifier_settings=MODIFIER_SETTINGS)
        self.row,self.mc,self.budget=row,mc,budget
        self.mc_document=mc.document()
        self.class_order=tuple(c['id'] for c in self.mc_document['classes'])
        self.census=inspect_workspace(workspace,row["signal_samples"])
        self.replaced=set(self.census["signal_mc_names"])
        self.observed=pyhf.Workspace(workspace).data(self.original)[:self.original.config.nmaindata]
        self.names=list(row["initial_point"]["source"])
        self.nominal=np.zeros(self.original.config.nmaindata)
        for channel in workspace["channels"]:
            part=self.original.config.channel_slices[channel["name"]]
            for sample in channel["samples"]:
                if sample["name"] in row["signal_samples"][channel["name"]]:self.nominal[part]+=sample["data"]
        self.permutation=[mc.bin_index(r["mc_bin_id"]) for r in row["source_bin_map"]]
        self.aux=[]
        for model,replacement in ((self.original,False),(self.bg,True)):
            for name in model.config.auxdata_order:
                if (name in self.replaced)!=replacement:continue
                pset=model.config.param_set(name);part=model.config.par_map[name]["slice"]
                for i in range(pset.n_parameters):
                    self.aux.append({"coordinate":model.config.par_names[part.start+i],"pdf":pset.pdf_type,"sigma":float(getattr(pset,"sigmas",[1.]*pset.n_parameters)[i]),"factor":float(getattr(pset,"factors",[1.]*pset.n_parameters)[i]),"observed":float(pset.auxdata[i])})
    def _means(self,source,poi,unit_MC=False):
        self.budget.charge("pyhf_main_calls")
        vector=list(self.original.config.suggested_init())
        for i,name in enumerate(self.original.config.par_names):
            if name==self.original.config.poi_name:vector[i]=poi
            elif name in source:vector[i]=source[name]
        if unit_MC:
            for name in self.replaced:
                part=self.original.config.par_map[name]["slice"];vector[part]=[1.]*(part.stop-part.start)
        means=np.asarray(self.original.expected_actualdata(vector));self.budget.check()
        return means
    def evaluate(self,point):
        self.budget.charge("density_wrapper_calls")
        source,latent=point["source"],point["latent"]
        _keys(source,self.names,label="complete independent source point")
        _keys(latent,self.class_order,label="complete independent MC point")
        mu=_number(point['mu'],'independent mu')
        if mu<0:raise ValueError('negative independent mu')
        background=self._means(source,0.)
        published=self._means(source,1.,True)-self._means(source,0.,True)
        probabilities=[_number(latent[name],'independent probability') for name in self.class_order]
        if any(p<0 or p>1 for p in probabilities) or abs(math.fsum(probabilities)-1)>1e-12:raise ValueError('independent complete simplex required')
        classes=self.mc_document['classes'];design=self.mc_document['mc_design']
        denominator=math.fsum(c['denominator_mark']*p for c,p in zip(classes,probabilities))
        raw=[math.fsum(c['contribution'][i]*p for c,p in zip(classes,probabilities)) for i in range(len(self.permutation))]
        if denominator<=0 or any(v<0 or not math.isfinite(v) for v in raw):raise ValueError('independent latent denominator/NET expectation refused')
        nominal=np.array([design['kappa']*v/denominator for v in raw])[self.permutation]
        signal=nominal*published/self.nominal
        main=background+mu*signal
        if any(not np.all(np.isfinite(v)) or np.any(v<0) for v in (background,published,signal,main)):raise ValueError("independent source physical expectation refused")
        terms=list(poisson.logpmf(self.observed,main));auxmeans=[]
        for row in self.aux:
            self.budget.charge("source_auxiliary_factor_calls")
            parameter=source[row["coordinate"]]
            mean=parameter if row["pdf"]=="normal" else row["factor"]*parameter
            auxmeans.append(mean)
            # HistFactory can supply noninteger effective auxiliary counts;
            # use its original log-factor convention, not scipy's discrete
            # support mask (which would incorrectly turn these into -inf).
            terms.append(float(norm.logpdf(row["observed"],parameter,row["sigma"])) if row["pdf"]=="normal" else float(xlogy(row["observed"],mean)-mean-gammaln(row["observed"]+1)))
        self.budget.charge("MC_density_calls")
        counts=[c['observed'] for c in classes]
        terms.append(float(multinomial.logpmf(counts,design["total_groups"],probabilities)))
        nll=-math.fsum(terms);self.budget.check()
        if not math.isfinite(nll):raise ValueError("independent source density nonfinite")
        return {"nll":nll,"main_means":main.tolist(),"background_means":background.tolist(),"signal_means":signal.tolist(),"distribution_mean_vector":main.tolist()+auxmeans+[design["total_groups"]*latent[name] for name in self.mc.class_ids]}


def _tangent_recipe(joint,bg,mc):
    domains=bg.contract()['active_parameter_domains']
    axes=['mu']+['source:'+name for name in bg.contract()['active_parameter_names'] if not domains[name]['fixed']]+['MC:'+name for name in mc.class_ids[:-1]]
    full=['mu']+['source:'+name for name in bg.contract()['active_parameter_names']]+['MC:'+name for name in mc.class_ids]
    projection=np.zeros((len(full),len(axes)))
    for i,name in enumerate(axes):
        projection[full.index(name),i]=1.
        if name.startswith('MC:'):projection[full.index('MC:'+mc.class_ids[-1]),i]=-1.
    return axes,projection


def _shift(point,axis,step,last):
    p=deepcopy(point)
    if axis=='mu':p['mu']+=step
    elif axis.startswith('source:'):p['source'][axis.removeprefix('source:')]+=step
    else:
        p['latent'][axis.removeprefix('MC:')]+=step;p['latent'][last]-=step
    return p


def _close(a,b,atol,rtol):return bool(np.all(np.abs(np.asarray(a)-np.asarray(b))<=atol+rtol*np.maximum(np.abs(a),np.abs(b))))


def _oracle_point(oracle,point,journal,identity,**metadata):
    digest=hashlib.sha256(compact(point)).hexdigest()
    journal.write('independent_density',identity,'planned',point_sha256=digest,**metadata)
    journal.write('independent_density',identity,'running',point_sha256=digest,**metadata)
    try:
        result=oracle.evaluate(point)
        journal.write('independent_density',identity,'completed',point_sha256=digest,result=result,**metadata)
        return result
    except Exception as error:
        journal.write('independent_density',identity,'failed',point_sha256=digest,error=str(error),exception_type=type(error).__name__,**metadata)
        raise


def _qualify(row,joint,bg,mc,oracle,limits,journal,outer_deadline,*,law_only=False):
    record={'case':row['id'],'fixed_vectors':[],'gradient_columns':[],'passed':False}
    analytic={}
    for field in ('initial_point','interior_point'):
        identity=row['id']+'/'+field;point=row[field]
        journal.write('qualification_point',identity,'planned',point=point)
        journal.write('qualification_point',identity,'running',point=point)
        entry=None
        try:
            if time.monotonic()>=outer_deadline:raise TimeoutError('outer work deadline')
            if law_only:oracle.budget.check()
            a=joint.evaluate_with_gradient(point['source'],point['latent'],mu=point['mu'])
            if law_only:
                entry={'identity':field,'point':point,'analytic':a,'independent':None,'passed':False}
                record['fixed_vectors'].append(entry)
                journal.write('qualification_analytic',identity,'returned',snapshot=a)
                oracle.budget.check()
            b=_oracle_point(oracle,point,journal,identity+'/oracle')
            passed=_close(a['source']['main_means'],b['main_means'],limits['mean_atol'],limits['mean_rtol']) and _close(a['source']['background_means'],b['background_means'],limits['mean_atol'],limits['mean_rtol']) and _close(a['source']['signal_means'],b['signal_means'],limits['mean_atol'],limits['mean_rtol']) and abs(a['nll']-b['nll'])<=limits['nll_atol']
            if law_only:entry.update(independent=b,passed=bool(passed))
            else:
                entry={'identity':field,'point':point,'analytic':a,'independent':b,'passed':bool(passed)};record['fixed_vectors'].append(entry)
            analytic[field]=a
            journal.write('qualification_point',identity,'completed',passed=bool(passed))
            if not passed:return record
        except Exception as error:
            failure={'identity':field,'point':point,'passed':False,'error':str(error),'exception_type':type(error).__name__}
            if law_only and entry is not None:entry.update(failure)
            else:record['fixed_vectors'].append(failure)
            journal.write('qualification_point',identity,'failed',error=str(error),exception_type=type(error).__name__);return record
    axes,projection=_tangent_recipe(joint,bg,mc);interior=row['interior_point'];a=analytic['interior_point']
    score=np.asarray(a['gradient'])@projection;mean_jac=np.asarray(a['distribution_mean_jacobian'])@projection
    for column,axis in enumerate(axes):
        identity=row['id']+'/gradient/'+axis
        journal.write('qualification_gradient',identity,'planned',coordinate=axis)
        journal.write('qualification_gradient',identity,'running',coordinate=axis)
        entry={'coordinate':axis,'analytic_score':float(score[column]),'analytic_mean_column':mean_jac[:,column].tolist(),'steps':[],'passed':False}
        try:
            for h in limits['steps']:
                samples=[]
                for sign in (-1,1):
                    point=_shift(interior,axis,sign*h,mc.class_ids[-1])
                    samples.append(_oracle_point(oracle,point,journal,identity+f'/h{h}/sign{sign}',coordinate=axis,step=h,sign=sign))
                fd=(samples[1]['nll']-samples[0]['nll'])/(2*h)
                jfd=(np.asarray(samples[1]['distribution_mean_vector'])-np.asarray(samples[0]['distribution_mean_vector']))/(2*h)
                score_error=abs(fd-score[column]);mean_error=np.abs(jfd-mean_jac[:,column])
                passed=_close(fd,score[column],limits['gradient_atol'],limits['gradient_rtol']) and _close(jfd,mean_jac[:,column],limits['gradient_atol'],limits['gradient_rtol'])
                entry['steps'].append({'h':h,'independent_score':float(fd),'independent_mean_column':jfd.tolist(),'score_absolute_error':float(score_error),
                                       'mean_absolute_errors':mean_error.tolist(),'mean_max_absolute_error':float(np.max(mean_error)),
                                       'score_relative_error':float(score_error/abs(score[column])) if score[column] else None,'mean_relative_errors':[float(e/abs(v)) if v else None for e,v in zip(mean_error,mean_jac[:,column])],
                                       'score_scaled_error':float(score_error/(limits['gradient_atol']+limits['gradient_rtol']*max(abs(fd),abs(score[column])))),
                                       'mean_max_scaled_error':float(np.max(mean_error/(limits['gradient_atol']+limits['gradient_rtol']*np.maximum(np.abs(jfd),np.abs(mean_jac[:,column]))))), 'passed':bool(passed)})
            large,small=entry['steps'];entry['score_step_drift']=abs(large['independent_score']-small['independent_score'])
            entry['mean_step_drifts']=np.abs(np.asarray(large['independent_mean_column'])-np.asarray(small['independent_mean_column'])).tolist()
            entry['passed']=bool(all(r['passed'] for r in entry['steps']) and _close(large['independent_score'],small['independent_score'],limits['gradient_atol'],limits['gradient_rtol']) and _close(large['independent_mean_column'],small['independent_mean_column'],limits['gradient_atol'],limits['gradient_rtol']))
            journal.write('qualification_gradient',identity,'completed',passed=entry['passed'])
        except Exception as error:
            entry.update(error=str(error),exception_type=type(error).__name__)
            journal.write('qualification_gradient',identity,'failed',error=str(error),exception_type=type(error).__name__)
        record['gradient_columns'].append(entry)
        if not entry['passed']:return record
    record['passed']=True;return record


def _endpoint_checks(fit,oracle,journal,identity,limits):
    records=[]
    for attempt in fit.get('attempts',[]):
        if 'parameters' not in attempt or 'nll' not in attempt:
            records.append({'attempt':attempt['index'],'checked':False,'passed':None,'reason':'No retained endpoint parameters/NLL; intermediate solver state is unavailable'})
            continue
        point=attempt['parameters'];label=identity+'/attempt'+str(attempt['index'])
        try:
            independent=_oracle_point(oracle,point,journal,label)
            density_error=abs(attempt['nll']-independent['nll'])
            means=attempt['distribution_mean_vector'];passed=density_error<=limits['nll_atol'] and _close(means,independent['distribution_mean_vector'],limits['mean_atol'],limits['mean_rtol'])
            records.append({'attempt':attempt['index'],'checked':True,'independent':independent,'nll_absolute_error':density_error,'passed':bool(passed)})
        except Exception as error:records.append({'attempt':attempt['index'],'checked':True,'passed':False,'error':str(error),'exception_type':type(error).__name__})
    available=[row for row in records if row['checked']]
    selected=[]
    if 'parameters' in fit and 'nll' in fit:
        for attempt in fit.get('attempts',[]):
            checked=next((row for row in available if row['attempt']==attempt['index'] and row['passed']),None)
            if checked and compact(fit['parameters'])==compact(attempt['parameters']) and fit['nll']==attempt['nll']:selected.append(attempt['index'])
    fit['selected_endpoint_binding']={'reported':bool('parameters' in fit and 'nll' in fit),'matching_independently_checked_attempts':selected,'passed':bool(selected),
                                     'rule':'Exact canonical parameters and exact NLL must match a retained independently checked attempt; no unlinked selected result can drive a statistic'}
    required_selected=not fit.get('verified') or bool(selected)
    fit['independent_endpoint_checks']=records
    fit['independent_endpoint_parity']=bool(available and all(r['passed'] for r in available) and required_selected)
    fit['independent_endpoint_scope']='Every available retained endpoint checked; missing solver endpoint states are explicit and remain unavailable'
    if not fit['independent_endpoint_parity']:fit['verified']=False;fit['independent_endpoint_refusal']='original-source endpoint parity missing or failed'
    return fit


def run(task,base_dir,output_dir):
    out=fm._admit_output(output_dir) # before capture, compilation or inference
    document,captured,background,cases=_capture(task,base_dir)
    started=time.monotonic();deadline=started+document['outer_work_seconds'];journal=Journal(out)
    law_only=_law_only(document)
    planned=[] if law_only else [{'case':r['id'],'construction':c,'hypothesis':h,'free_dimension':r['expected_free_coordinates']-(len(mc.class_ids)-1 if c=='fixed_MC_baseline' else 0)-(1 if h=='fixed_strength' else 0)} for r,_,mc in cases for c in ('fixed_MC_baseline','finite_MC') for h in ('free_strength','fixed_strength')]
    for row in planned:journal.write('fit',row['case']+'/'+row['construction']+'/'+row['hypothesis'],'planned',recipe=row)
    qbudget=QualificationBudget(document['qualification'],deadline);compiled=[];qualification=[];fits=[];fatal=None
    endpoint_counts={key:0 for key in qbudget.used}
    try:
        for row,workspace,mc in cases:
            if time.monotonic()>=deadline:raise TimeoutError('outer work deadline')
            bg,joint=_compile(row,workspace,background,mc,document['measurement'],document['model_id'])
            oracle=IndependentSourceOracle(workspace,background,row,mc,document['measurement'],qbudget)
            # Compiler inspection alone is separate from actual qualification.
            compiled.append((row,bg,joint,mc,oracle))
            result=_qualify(row,joint,bg,mc,oracle,document['qualification'],journal,deadline,law_only=law_only);qualification.append(result)
            if not result['passed']:break
        if not law_only and len(qualification)==len(cases) and all(r['passed'] for r in qualification):
            for row,bg,joint,mc,oracle in compiled:
                profiler=AnalyticJointProfiler(joint,bg,mc,mu_domain=document['fit']['mu_domain'],source_bound_semantics=row['source_bound_semantics'],rate_caps={})
                outputs={}
                for construction in ('fixed_MC_baseline','finite_MC'):
                    outputs[construction]={}
                    for hypothesis in ('free_strength','fixed_strength'):
                        identity=row['id']+'/'+construction+'/'+hypothesis
                        journal.write('fit',identity,'running',free_source_coordinates=bg.contract()['active_parameter_names'],MC_conditioned=construction=='fixed_MC_baseline',fixed_mu=document['fit']['fixed_strength'] if hypothesis=='fixed_strength' else None)
                        try:
                            fitted=profiler.fit(fixed_mu=document['fit']['fixed_strength'] if hypothesis=='fixed_strength' else None,
                                                fixed_latent=row['initial_point']['latent'] if construction=='fixed_MC_baseline' else None,
                                                budget=document['fit']['budget_per_fit'],wall_hook=lambda:time.monotonic()>=deadline)
                            # Serialize the returned solver object before an
                            # endpoint check or later fit can be interrupted.
                            journal.write('fit',identity,'returned',snapshot=fitted,
                                          scope='Returned fit object retained; current future solver memory is not serialized')
                            ep=document['fit']['endpoint_verification'];ebudget=QualificationBudget(ep,deadline);oracle.budget=ebudget
                            fitted=_endpoint_checks(fitted,oracle,journal,identity,document['qualification'])
                            for key,value in ebudget.used.items():endpoint_counts[key]+=value
                            outputs[construction][hypothesis]=fitted
                            journal.write('fit',identity,'completed',verified=bool(fitted['verified']),status=fitted['status'],endpoint_budget_used=ebudget.used,snapshot=fitted)
                        except Exception as error:
                            outputs[construction][hypothesis]={'verified':False,'status':'fit_or_endpoint_exception','error':str(error),'exception_type':type(error).__name__}
                            journal.write('fit',identity,'failed',error=str(error),exception_type=type(error).__name__)
                fits.append({'case':row['id'],'fits':outputs})
                if time.monotonic()>=deadline:break
    except Exception as error:
        fatal={'error':str(error),'exception_type':type(error).__name__};journal.write('stage','full-source-qualification','failed',**fatal)
    nested=[]
    for case in fits:
        for hypothesis in ('free_strength','fixed_strength'):
            baseline=case['fits']['fixed_MC_baseline'][hypothesis];full=case['fits']['finite_MC'][hypothesis]
            delta=full['nll']-baseline['nll'] if baseline.get('verified') and full.get('verified') else None
            nested.append({'case':case['case'],'hypothesis':hypothesis,'full_minus_conditioned_nll':delta,'passed':delta is not None and delta<=1e-5,'scope':'Feasible-set identity; violation or missing endpoint is unresolved optimization, not a physics effect'})
        for construction in ('fixed_MC_baseline','finite_MC'):
            rows=case['fits'][construction];free,fixed=rows['free_strength'],rows['fixed_strength']
            delta=2*(fixed['nll']-free['nll']) if free.get('verified') and fixed.get('verified') else None
            rows['twice_delta_nll']=max(0.,delta) if delta is not None and delta>=-1e-5 else None
    qualified=not fatal and len(qualification)==len(cases) and all(r['passed'] for r in qualification)
    status=qualified if law_only else qualified and len(fits)==len(cases) and all(r['passed'] for r in nested) and all(c['fits'][kind]['twice_delta_nll'] is not None for c in fits for kind in ('fixed_MC_baseline','finite_MC'))
    result={'schema_version':1,'model_id':document['model_id'],'status':'passed' if status else 'failed','physics_validated':False,'global_optimum_certified':False,'qualification':qualification,'fits':fits,'nested_model_checks':nested,'fatal':fatal,
            'planned_fit_denominator':len(planned),'completed_fit_records':sum(2 for _ in fits)*2,'qualification_budget_used':qbudget.used,'endpoint_verification_budget_used':endpoint_counts,'resource_bounds':_bounds(document),
            'elapsed_seconds':time.monotonic()-started,'source_inputs':[{'path':p,'sha256':hashlib.sha256(data).hexdigest()} for p,data in captured.items()],
            'limits':['Controlled fixed-mark/source response extension, not native generator or variation authority.','Local multistart/rank/stationarity are not globality or finite-endpoint proof; source-dependent mu recession remains unresolved.','No calibration, CLs or exclusion claim.','Hard timeout retains journal started identities, not un-serialized intermediate solver state.']}
    if law_only:
        result.update(schema_version=2,execution_scope='law_only',law_qualification_passed=bool(qualified),profile_qualification_performed=False,
                      claim_scope='Supplied full-law values at the exact initial and interior points, and all declared tangent derivatives at the interior point only; no numerical optimum, profile, calibration or CLs qualification')
        result['limits'].append('Law-only execution has zero fit/optimizer/LP calls; schema1 combined requests never fall back to this scope.')
    for p,raw in captured.items():
        if _read(Path(p))!=raw:raise ValueError('qualification inputs changed during execution')
    journal.write('stage','full-source-qualification','completed',status=result['status'])
    payloads={'joint_qualification_contract.json':document,'joint_qualification_result.json':result,'joint_qualification_compiled.json':[{'case':r['id'],'background':bg.contract(),'joint':joint.contract()} for r,bg,joint,mc,oracle in compiled]}
    serialized={name:compact(value) for name,value in payloads.items()}
    if sum(map(len,serialized.values()))>MAX_RESULT_BYTES:raise ValueError('result byte budget exceeded')
    if {p.name for p in out.iterdir()}!={'qualification-progress.jsonl'}:raise FileExistsError('output changed after fresh admission')
    for name,raw in serialized.items():
        with (out/name).open('xb') as stream:stream.write(raw)
    return result
