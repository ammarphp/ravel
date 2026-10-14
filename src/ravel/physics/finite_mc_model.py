"""Source-bound exact fixed-mark MC families under supplied generator laws.

Poisson groups: m_k~Pois(t_k*rho_k), s=W*rho.
Fixed N: m~Mult(N,p), s=kappa*(A*p)/(d.p), including unselected support.
Main SR/CR observations are disjoint Pois(b_i+mu*s_i). Observed signed MC
summaries may be negative. Only latent physical expectations are constrained.
Exactness is conditional on the declared generator law and fixed known marks;
ordinary native fixed-N/adaptive/continuous-weight samples are not Poissonized.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from ravel.physics.quantities import _keys, _number, _text
from ravel.physics.statistical_model import _load_bytes, _regular

KINDS = ("poisson_groups", "fixed_n_categories")
EXECUTION_SECONDS = 60


def validate(task):
    _keys(task,("input",),label="finite MC task")
    _text(task["input"],"input")
    return deepcopy(task)


def _numbers(values,size,label):
    if not isinstance(values,list) or len(values) != size:
        raise ValueError(f"{label} needs {size} entries")
    return [_number(v,label) for v in values]


def _ids(values,label,empty=False):
    if not isinstance(values,list) or not empty and not values:
        raise ValueError(f"{label} needs an explicit list")
    for value in values:
        _text(value,label)
    if len(set(values)) != len(values):
        raise ValueError(f"duplicate {label}")


def prepare(document):
    _keys(document,("schema_version","model_id","sources","bins","partition","background_contract",
                    "mc_design","classes","mu","comparison_points","profile_points","calibration","assumptions"),label="finite MC model")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("unsupported model schema")
    _text(document["model_id"],"model id")
    if not isinstance(document["sources"],list) or not document["sources"]:
        raise ValueError("byte-bound scientific and generator sources required")
    for pin in document["sources"]:
        _keys(pin,("id","path","sha256","reference"),label="source pin")
        for key in ("id","path","reference"):
            _text(pin[key],key)
        if not isinstance(pin["sha256"],str) or len(pin["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in pin["sha256"]):
            raise ValueError("source SHA256 invalid")
    source_ids=[p["id"] for p in document["sources"]]
    _ids(source_ids,"source ids")
    def source(value):
        if value not in source_ids:
            raise ValueError("unknown source reference")
    bins=document["bins"]
    if not isinstance(bins,list) or not 2 <= len(bins) <= 8:
        raise ValueError("two to eight disjoint main SR/CR bins required")
    for row in bins:
        _keys(row,("id","role","observed","background","observation_id","source"),label="main bin")
        for key in ("id","observation_id"):
            _text(row[key],key)
        if row["role"] not in ("signal","control") or type(row["observed"]) is not int or row["observed"]<0:
            raise ValueError("main bins require signal/control role and integer observations")
        if not 0 < _number(row["background"],"conditional background") <= 1e6:
            raise ValueError("first restricted family requires positive supplied fixed backgrounds")
        source(row["source"])
    _ids([b["id"] for b in bins],"bin ids")
    _ids([b["observation_id"] for b in bins],"observation ids")
    if {b["role"] for b in bins} != {"signal","control"}:
        raise ValueError("both SR and CR observations required")
    _keys(document["partition"],("kind","source","overlap_counts"),label="partition")
    source(document["partition"]["source"])
    overlap=document["partition"]["overlap_counts"]
    if document["partition"]["kind"] != "disjoint" or not isinstance(overlap,list) or len(overlap)!=len(bins):
        raise ValueError("supplied disjoint partition matrix required")
    for i,row in enumerate(overlap):
        if not isinstance(row,list) or len(row)!=len(bins) or any(type(x) is not int or x<0 for x in row):
            raise ValueError("partition overlap counts must be integer matrix")
        if any(x != (bins[i]["observed"] if i==j else 0) for j,x in enumerate(row)):
            raise ValueError("known overlaps cannot become independent main Poisson factors")
    _keys(document["background_contract"],("mode","source","meaning"),label="background contract")
    if document["background_contract"]["mode"] != "conditional_fixed":
        raise ValueError("background nuisances require an explicit later joint construction")
    source(document["background_contract"]["source"])
    _text(document["background_contract"]["meaning"],"background interpretation")
    design=document["mc_design"]
    _keys(design,("kind","sampling_law","fixed_marks","support_complete","ledger_source","independence",
                  "total_groups","kappa","normalization_source","normalization_meaning"),label="MC design")
    if design["kind"] not in KINDS:
        raise ValueError("moments alone do not determine an MC sampling law")
    if design["fixed_marks"] is not True or design["support_complete"] is not True:
        raise ValueError("complete known fixed-mark support required, including zero-observed classes")
    source(design["ledger_source"])
    source(design["normalization_source"])
    _text(design["normalization_meaning"],"normalization meaning")
    if design["kind"]=="poisson_groups":
        if design["sampling_law"] != "independent_poisson_fixed_mark_populations" or design["independence"] != "disjoint_poisson_group_populations":
            raise ValueError("Poisson exactness needs an actual Poissonized group sampling design")
        if design["total_groups"] is not None or design["kappa"] is not None:
            raise ValueError("fixed total N and inclusive ratio normalization cannot be silently Poissonized")
    else:
        if design["sampling_law"] != "iid_fixed_mark_categories" or design["independence"] != "iid_groups_within_one_fixed_N_stream":
            raise ValueError("fixed-N law requires IID complete categorical group design")
        if type(design["total_groups"]) is not int or not 1 <= design["total_groups"] <= 100000:
            raise ValueError("complete fixed total generated group count required")
        if not 0 < _number(design["kappa"],"known external inclusive expectation") <= 1e6:
            raise ValueError("fixed-N normalization requires positive known external kappa")
    classes=document["classes"]
    if not isinstance(classes,list) or not 1 <= len(classes) <= 8:
        raise ValueError("one to eight declared MC group classes required")
    group_ids=[]
    for item in classes:
        _keys(item,("id","contribution","denominator_mark","exposure","observed","observed_group_ids","initial","upper","source"),label="MC class")
        _text(item["id"],"class id")
        source(item["source"])
        _numbers(item["contribution"],len(bins),"per-group contribution")
        if type(item["observed"]) is not int or item["observed"]<0:
            raise ValueError("MC auxiliary observations are integer group counts, never signed sums")
        _ids(item["observed_group_ids"],"observed group ids",empty=True)
        if len(item["observed_group_ids"])!=item["observed"]:
            raise ValueError("each observed MC group needs one globally unique identity")
        group_ids.extend(item["observed_group_ids"])
        initial=_number(item["initial"],"initial nuisance")
        upper=_number(item["upper"],"nuisance upper bound")
        if design["kind"]=="poisson_groups":
            if not 0 < _number(item["exposure"],"known MC/target exposure") <= 1e6 or item["denominator_mark"] is not None:
                raise ValueError("Poisson strata require known exposure and no random ratio denominator")
            if not 0 < initial < upper <= 1e5:
                raise ValueError("Poisson rates need positive interior starts and finite numerical upper caps")
        else:
            _number(item["denominator_mark"],"inclusive per-group denominator mark")
            if item["exposure"] is not None or upper != 1. or not 0 < initial < 1:
                raise ValueError("fixed-N probabilities require full simplex, no Poisson exposure or extra probability caps")
    _ids([c["id"] for c in classes],"class ids")
    _ids(group_ids,"globally unique observed groups",empty=True)
    if design["kind"]=="fixed_n_categories":
        if len(classes)<2 or sum(c["observed"] for c in classes)!=design["total_groups"]:
            raise ValueError("fixed N includes unselected groups and all zero-observed declared support")
        if abs(sum(c["initial"] for c in classes)-1)>1e-12:
            raise ValueError("initial probabilities must sum exactly to one; no implicit last-category replacement")
    _keys(document["mu"],("initial","upper","meaning"),label="mu")
    if not 0 < _number(document["mu"]["initial"],"mu initial") < _number(document["mu"]["upper"],"mu upper") <= 1000:
        raise ValueError("mu uses physical lower zero and explicit numerical upper cap")
    _text(document["mu"]["meaning"],"mu meaning")
    points=document["comparison_points"]
    if not isinstance(points,list) or not 2 <= len(points) <= 16:
        raise ValueError("frozen original-density comparisons required")
    for point in points:
        _point(document,point)
    initial={"mu":document["mu"]["initial"],"nuisance":{c["id"]:c["initial"] for c in classes}}
    _point(document,initial)
    if any(not any(c["contribution"][i]!=0 for c in classes) for i in range(len(bins))):
        raise ValueError("every SR/CR needs explicit signal-support marks, even when observed selected count is zero")
    profiles=document["profile_points"]
    if not isinstance(profiles,list) or not profiles or len(profiles)>16 or any(not 0 <= _number(m,"profile mu") <= document["mu"]["upper"] for m in profiles):
        raise ValueError("bounded mu profile grid required")
    cal=document["calibration"]
    _keys(cal,("enabled","seed","trials_per_truth","truths","nuisance_sampling","main_sampling","mc_sampling","threshold","confidence_level","maxiter"),label="calibration")
    if type(cal["enabled"]) is not bool or type(cal["seed"]) is not int or not 0<=cal["seed"]<2**32:
        raise ValueError("explicit calibration toggle and uint32 seed required")
    if type(cal["trials_per_truth"]) is not int or not 1<=cal["trials_per_truth"]<=200:
        raise ValueError("first staged calibration ceiling is 200 trials per truth")
    if not isinstance(cal["truths"],list) or not 1<=len(cal["truths"])<=4:
        raise ValueError("one to four frozen nuisance truth settings required")
    for truth in cal["truths"]:
        _point(document,truth)
    if cal["nuisance_sampling"]!="fixed_truth" or cal["main_sampling"]!="repeat_poisson_main" or cal["mc_sampling"]!="repeat_declared_MC_law":
        raise ValueError("calibration must repeat main AND MC measurements at fixed nuisance truths")
    if not 0<_number(cal["threshold"],"threshold")<=100 or not 0<_number(cal["confidence_level"],"confidence level")<1:
        raise ValueError("explicit LR inclusion threshold and ensemble interval confidence required")
    if type(cal["maxiter"]) is not int or not 20<=cal["maxiter"]<=2000:
        raise ValueError("bounded optimizer budget required")
    if not isinstance(document["assumptions"],list) or len(document["assumptions"])<3:
        raise ValueError("source/generator/physical assumptions required")
    for text in document["assumptions"]:
        _text(text,"assumption")
    return deepcopy(document)


def _point(document,point):
    _keys(point,("mu","nuisance"),label="parameter point")
    if not 0<=_number(point["mu"],"mu")<=document["mu"]["upper"]:
        raise ValueError("mu exceeds numerical search bounds")
    _keys(point["nuisance"],[c["id"] for c in document["classes"]],label="complete nuisance point")
    values=[]
    for c in document["classes"]:
        x=_number(point["nuisance"][c["id"]],"nuisance")
        if not 0<=x<=c["upper"]:
            raise ValueError("negative latent rates/probabilities or exceeded numerical caps")
        values.append(x)
    try:
        numerators=[math.fsum(c["contribution"][i]*x for c,x in zip(document["classes"],values)) for i in range(len(document["bins"]))]
    except (OverflowError,ValueError) as error:
        raise ValueError("NET expectation overflows finite arithmetic") from error
    if any(not math.isfinite(x) for x in numerators):
        raise ValueError("NET expectation overflows finite arithmetic")
    if any(x < 0 for x in numerators):
        raise ValueError("negative physical NET expectation; observed signed arithmetic is never clipped")
    if document["mc_design"]["kind"]=="fixed_n_categories":
        if abs(sum(values)-1)>1e-12:
            raise ValueError("complete categorical probabilities must sum to one")
        try:
            denominator=math.fsum(c["denominator_mark"]*x for c,x in zip(document["classes"],values))
        except (OverflowError,ValueError) as error:
            raise ValueError("expected denominator overflows finite arithmetic") from error
        if not math.isfinite(denominator):
            raise ValueError("expected denominator overflows finite arithmetic")
        if denominator<=0:
            raise ValueError("signed normalization requires a positive expected denominator")
    return point


def _capture(task,base):
    path=_regular(validate(task)["input"],base)
    raw=path.read_bytes()
    document=prepare(_load_bytes(raw))
    captured={str(path):raw}
    source_by_id={}
    for pin in document["sources"]:
        p=_regular(pin["path"],path.parent)
        data=p.read_bytes()
        if hashlib.sha256(data).hexdigest()!=pin["sha256"]:
            raise ValueError("finite MC source hash mismatch: "+pin["id"])
        captured[str(p)]=data
        source_by_id[pin["id"]]=data
    ledger=_load_bytes(source_by_id[document["mc_design"]["ledger_source"]])
    _keys(ledger,("schema_version","sampling_law","support_complete","classes","groups","normalization","main_bins","main_partition"),label="MC ledger")
    main_expected=[{key:b[key] for key in ("id","role","observed","background","observation_id")} for b in document["bins"]]
    if ledger["main_bins"]!=main_expected or ledger["main_partition"]!={key:document["partition"][key] for key in ("kind","overlap_counts")}:
        raise ValueError("source-bound main observations/background/partition mismatch")
    expected=[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in document["classes"]]
    if type(ledger["schema_version"]) is not int or ledger["schema_version"]!=1 or ledger["classes"]!=expected or ledger["support_complete"] is not True or ledger["sampling_law"]!=document["mc_design"]["sampling_law"]:
        raise ValueError("source-bound complete class/mark/sampling support does not match input")
    norm={key:document["mc_design"][key] for key in ("total_groups","kappa","normalization_meaning")}
    if ledger["normalization"]!=norm:
        raise ValueError("source-bound exposure/normalization meaning mismatch")
    groups=ledger["groups"]
    if not isinstance(groups,list):
        raise ValueError("complete observed MC group ledger required")
    observed={c["id"]:[] for c in document["classes"]}
    for group in groups:
        _keys(group,("id","class_id","contribution","denominator_mark"),label="observed group")
        if group["class_id"] not in observed:
            raise ValueError("observed group has undeclared class")
        c=next(c for c in document["classes"] if c["id"]==group["class_id"])
        if group["contribution"]!=c["contribution"] or group["denominator_mark"]!=c["denominator_mark"]:
            raise ValueError("random/unequal observed marks cannot use fixed-mark model")
        observed[c["id"]].append(group["id"])
    for c in document["classes"]:
        if observed[c["id"]]!=c["observed_group_ids"]:
            raise ValueError("observed group multiplicity/identity mismatch")
    for p,data in captured.items():
        if Path(p).read_bytes()!=data:
            raise ValueError("model/source changed during capture")
    return document,captured


def inputs(task,base_dir):
    _,captured=_capture(task,base_dir)
    return [Path(p) for p in captured]


def resource_bounds(task,base_dir):
    """Read-only upper work counts for the exact supplied bounded recipe."""
    document,_=_capture(task,base_dir)
    return _resource_bounds(document)


def _resource_bounds(document):
    protocol=document["calibration"]
    trials=len(protocol["truths"])*protocol["trials_per_truth"] if protocol["enabled"] else 0
    # The observed profile has one free fit and every declared fixed-mu fit;
    # each trial has one free fit and one fixed-truth fit. Every fit has at most
    # three starts, each with the supplied iteration ceiling. These are work
    # counts, not an estimated runtime or a global-optimum certificate.
    fit_count=1+len(document["profile_points"])+2*trials
    seed_lp_per_fit=2*len(document["classes"]) if document["mc_design"]["kind"]=="fixed_n_categories" else 0
    return {"execution_seconds":EXECUTION_SECONDS,"processes":1,"threads":1,
            "main_bins":len(document["bins"]),"latent_MC_coordinates":len(document["classes"]),
            "comparison_points":len(document["comparison_points"]),"calibration_trial_denominator":trials,
            "maximum_fit_calls":fit_count,"maximum_optimizer_attempts":3*fit_count,
            "maximum_iterations_per_attempt":protocol["maxiter"],
            "maximum_total_optimizer_iterations":3*fit_count*protocol["maxiter"],
            "maximum_seed_feasibility_LP_calls":seed_lp_per_fit*fit_count,
            "maximum_endpoint_stationarity_LP_calls":3*fit_count,
            "enforcement":"60-second wall ceiling belongs to the approved scientific-study supervisor; work counts can stop earlier on unresolved arithmetic or structural limits"}


def execution_seconds(task,base_dir):
    """Admission hook for the outer approved scientific-study supervisor."""
    return resource_bounds(task,base_dir)["execution_seconds"]


def export_fixed_mark_ledger(groups,declared_support,sampling_law,normalization):
    """Raw-group design export before any signed observed normalization.

    Support must be supplied independently of observed groups. Zero-observed
    classes survive, and unequal/random marks or unknown classes are refused.
    This validates records; it cannot establish an IID/Poisson generator law.
    """
    if sampling_law not in ("independent_poisson_fixed_mark_populations","iid_fixed_mark_categories"):
        raise ValueError("raw-event exporter requires an explicit supported generator law")
    if not isinstance(declared_support,list) or not declared_support:
        raise ValueError("complete declared support required; cannot infer support from observed events")
    ids=[];size=None
    for row in declared_support:
        _keys(row,("id","contribution","denominator_mark","exposure"),label="declared fixed-mark support")
        ids.append(_text(row["id"],"support id"))
        if size is None:
            if not isinstance(row["contribution"],list) or not 2<=len(row["contribution"])<=8:
                raise ValueError("raw support needs complete two-to-eight-bin contribution vectors")
            size=len(row["contribution"])
        _numbers(row["contribution"],size,"raw fixed contribution")
        if sampling_law=="iid_fixed_mark_categories":
            _number(row["denominator_mark"],"raw denominator mark")
            if row["exposure"] is not None:
                raise ValueError("fixed-N support cannot carry Poisson exposure")
        elif row["denominator_mark"] is not None or not 0<_number(row["exposure"],"raw known exposure")<=1e6:
            raise ValueError("Poisson support requires known exposure and no ratio denominator")
    _ids(ids,"declared support ids")
    if any(not any(row["contribution"][i]!=0 for row in declared_support) for i in range(size)):
        raise ValueError("every raw SR/CR bin needs independently declared possible signal support")
    if not isinstance(groups,list):
        raise ValueError("observed raw groups must be a complete list")
    counts={name:0 for name in ids};observed_ids=[]
    for group in groups:
        _keys(group,("id","class_id","contribution","denominator_mark"),label="raw group")
        observed_ids.append(_text(group["id"],"raw group id"))
        if group["class_id"] not in counts:
            raise ValueError("raw event has undeclared support; no empirical-support completion")
        row=declared_support[ids.index(group["class_id"])]
        if any(group[key]!=row[key] for key in ("contribution","denominator_mark")):
            raise ValueError("observed weights are not fixed within the declared group class")
        counts[group["class_id"]]+=1
    _ids(observed_ids,"raw group ids",empty=True)
    _keys(normalization,("total_groups","kappa","normalization_meaning"),label="raw design normalization")
    _text(normalization["normalization_meaning"],"raw normalization meaning")
    if sampling_law=="iid_fixed_mark_categories":
        if type(normalization["total_groups"]) is not int or not 1<=normalization["total_groups"]<=100000 or normalization["total_groups"]!=len(groups):
            raise ValueError("fixed N must include every generated group, including unselected ones")
        if not 0<_number(normalization["kappa"],"raw external inclusive expectation")<=1e6:
            raise ValueError("fixed-N raw export requires known positive external kappa")
    elif normalization["total_groups"] is not None or normalization["kappa"] is not None:
        raise ValueError("Poisson raw export cannot silently accept fixed N or ratio normalization")
    ledger={"schema_version":1,"sampling_law":sampling_law,"support_complete":True,"classes":deepcopy(declared_support),
            "groups":deepcopy(groups),"normalization":deepcopy(normalization)}
    return {"ledger":ledger,"observed_counts_in_declared_support":counts,
            "limits":"Source must establish full support and generator design; event records alone do not prove them."}


def _data(document,data):
    if data is None:
        return [b["observed"] for b in document["bins"]],[c["observed"] for c in document["classes"]]
    _keys(data,("main","mc"),label="repeated joint observations")
    for key,size in (("main",len(document["bins"])),("mc",len(document["classes"]))):
        if not isinstance(data[key],list) or len(data[key])!=size or any(type(x) is not int or x<0 for x in data[key]):
            raise ValueError("repeated data require complete nonnegative integer counts")
    if document["mc_design"]["kind"]=="fixed_n_categories" and sum(data["mc"])!=document["mc_design"]["total_groups"]:
        raise ValueError("fixed-N repetitions must retain the complete total N")
    return data["main"],data["mc"]


def _poisson_nll(counts,means):
    from scipy.special import gammaln,xlogy
    import numpy as np
    counts,means=np.asarray(counts),np.asarray(means)
    return float(np.sum(means-xlogy(counts,means)+gammaln(counts+1)))


def evaluate(document,point,data=None):
    """Refuse derived overflow without emitting NaN/infinity diagnostics."""
    import numpy as np
    with np.errstate(over="raise",invalid="raise"):
        result=_evaluate(document,point,data)
    def check(value):
        if isinstance(value,list):
            for item in value:
                check(item)
        elif value is not None and not math.isfinite(value):
            raise ValueError("derived MC expectation, derivative or covariance overflows finite arithmetic")
    for key in ("main_means","signal_expectation","raw_mark_expectation","expected_denominator","mc_means","gradient","main_jacobian","mark_estimator_covariance"):
        check(result[key])
    if any(v<0 for v in result["signal_expectation"]):
        raise ValueError("numerical signal NET expectation violates physical support")
    if not result["finite"]:
        _,counts=_data(document,data)
        if not any(count>0 and mean==0 for count,mean in zip(counts,result["mc_means"])):
            raise ValueError("nonfinite density without a mathematical zero-probability auxiliary point")
    return result


def _evaluate(document,point,data=None):
    """Exact full joint likelihood for the declared law, including constants."""
    import numpy as np
    from scipy.special import gammaln,xlogy
    _point(document,point)
    n,m=_data(document,data)
    n,m=np.asarray(n),np.asarray(m)
    values=np.asarray([point["nuisance"][c["id"]] for c in document["classes"]])
    marks=np.asarray([c["contribution"] for c in document["classes"]]).T
    raw=marks@values
    kind=document["mc_design"]["kind"]
    if kind=="poisson_groups":
        signal=raw
        signal_jac=marks
        exposure=np.asarray([c["exposure"] for c in document["classes"]])
        mc_mean=exposure*values
        mc_nll=_poisson_nll(m,mc_mean)
        mc_grad=exposure-np.divide(m,values,out=np.zeros(len(m),dtype=float),where=values>0)
        covariance=marks @ np.diag(values/exposure)@marks.T
        denominator=None
    else:
        d=np.asarray([c["denominator_mark"] for c in document["classes"]])
        denominator=float(d@values)
        kappa=document["mc_design"]["kappa"]
        signal=kappa*raw/denominator
        signal_jac=kappa*(marks*denominator-raw[:,None]*d)/denominator**2
        N=document["mc_design"]["total_groups"]
        mc_mean=N*values
        mc_nll=float(-gammaln(N+1)+np.sum(gammaln(m+1)-xlogy(m,values)))
        mc_grad=-np.divide(m,values,out=np.zeros(len(m),dtype=float),where=values>0)
        # Exact covariance of unnormalized marks; ratio covariance is nonlinear.
        covariance=marks@(np.diag(values)-np.outer(values,values))@marks.T/N
    means=np.asarray([b["background"] for b in document["bins"]])+point["mu"]*signal
    nll=_poisson_nll(n,means)+mc_nll
    jac=np.column_stack([signal,point["mu"]*signal_jac])
    grad=jac.T@(1-n/means)
    grad[1:]+=mc_grad
    finite=math.isfinite(nll)
    return {"nll":nll if finite else None,"finite":finite,"zero_probability":not finite,"main_means":means.tolist(),"signal_expectation":signal.tolist(),
            "raw_mark_expectation":raw.tolist(),"expected_denominator":denominator,"mc_means":mc_mean.tolist(),
            "gradient":grad.tolist(),"main_jacobian":jac.tolist(),"mark_estimator_covariance":covariance.tolist(),
            "covariance_scope":"Poisson group sum/exposure exactly; fixed-N unnormalized mean marks exactly, not an exact ratio covariance"}


def independent_density(document,point,data=None):
    """Independent probability arithmetic; no producer likelihood/mean calls."""
    n,m=_data(document,data)
    vals=[point["nuisance"][c["id"]] for c in document["classes"]]
    net=[sum(c["contribution"][i]*v for c,v in zip(document["classes"],vals)) for i in range(len(n))]
    if document["mc_design"]["kind"]=="fixed_n_categories":
        d=sum(c["denominator_mark"]*v for c,v in zip(document["classes"],vals))
        signal=[document["mc_design"]["kappa"]*s/d for s in net]
    else:
        signal=net
    means=[b["background"]+point["mu"]*s for b,s in zip(document["bins"],signal)]
    def log_poisson(count,mean):
        if mean==0:
            return 0. if count==0 else -math.inf
        return -mean+count*math.log(mean)-math.lgamma(count+1)
    log_likelihood=sum(log_poisson(count,mean) for count,mean in zip(n,means))
    if document["mc_design"]["kind"]=="poisson_groups":
        log_likelihood+=sum(log_poisson(count,c["exposure"]*v) for c,count,v in zip(document["classes"],m,vals))
    else:
        log_likelihood+=math.lgamma(sum(m)+1)-sum(math.lgamma(count+1) for count in m)
        for count,v in zip(m,vals):
            if count:
                log_likelihood+=count*math.log(v) if v>0 else -math.inf
    return {"nll":-log_likelihood if math.isfinite(log_likelihood) else None,"finite":math.isfinite(log_likelihood),"main_means":means}


def identifiability(document,point):
    import numpy as np
    result=evaluate(document,point)
    K=len(document["classes"])
    auxiliary=np.zeros((K,K+1))
    auxiliary[:,1:]=np.diag([c["exposure"] for c in document["classes"]]) if document["mc_design"]["kind"]=="poisson_groups" else np.eye(K)*document["mc_design"]["total_groups"]
    matrix=np.vstack([result["main_jacobian"],auxiliary])
    if document["mc_design"]["kind"]=="fixed_n_categories":
        transform=np.zeros((K+1,K));transform[0,0]=1
        transform[1:K,1:]=np.eye(K-1);transform[K,1:]=-1
        matrix=matrix@transform
    norms=np.linalg.norm(matrix,axis=0)
    singular=np.linalg.svd(matrix/np.where(norms>0,norms,1),compute_uv=False)
    rank=int(np.sum(singular>max(singular[0]*1e-9,1e-12)))
    return {"identified":rank==matrix.shape[1],"rank":rank,"free_dimension":int(matrix.shape[1]),
            "singular_values":singular.tolist(),"nonregular_zero_rates_or_probabilities":any(v==0 for v in point["nuisance"].values()),
            "scope":"local mean-Jacobian rank in simplex tangent; not boundary asymptotic calibration"}


def structural_limits(document,data=None):
    """Expose a concrete zero-MC recession direction before numerical capping."""
    _,counts=_data(document,data)
    selected=[i for i,c in enumerate(document["classes"]) if any(w!=0 for w in c["contribution"])]
    all_zero=bool(selected and all(counts[i]==0 for i in selected))
    positive_unselected_denominator=all(c["denominator_mark"] is not None and c["denominator_mark"]>0 for i,c in enumerate(document["classes"]) if i not in selected)
    certified=all_zero and (document["mc_design"]["kind"]=="poisson_groups" or positive_unselected_denominator)
    return {"all_selected_MC_observed_zero":all_zero,"finite_mu_endpoint_not_established":all_zero,
            "analytic_scaling_recession":certified,
            "direction":"mu increases, selected rho/p decrease inversely; main signal stays finite while zero-count MC penalties approach their supremum" if certified else None,
            "limit":"An MC zero count is not a known zero rate. Numerical mu caps cannot supply physical information; signed denominator cases need their own recession analysis."}


START_SEPARATION = 1e-6


def _distinct_feasible_starts(document,init,bounds,free_mu,fixed_mu,W,m):
    """Generate actual feasible seeds, including conditional simplex fits.

    Linear programs only find feasible seed targets; they never optimize or
    certify the nonlinear likelihood. Convex mixing keeps the starting points
    inside the supplied signed NET/positive-denominator domain.
    """
    import numpy as np
    from scipy.optimize import linprog
    offset=int(free_mu);classes=document["classes"];starts=[];refused=[];lp_attempts=[]
    def point(x):
        return {"mu":float(x[0]) if free_mu else fixed_mu,"nuisance":{c["id"]:float(v) for c,v in zip(classes,x[offset:])}}
    def append(x,origin):
        x=np.asarray(x,dtype=float)
        try:
            if not np.all(np.isfinite(x)):
                raise ValueError("seed has nonfinite coordinates")
            if any(not lo<=v<=hi for v,(lo,hi) in zip(x,bounds)):
                raise ValueError("seed lies outside numerical search bounds")
            _point(document,point(x))
            if document["mc_design"]["kind"]=="fixed_n_categories" and math.fsum(c["denominator_mark"]*v for c,v in zip(classes,x[offset:]))<1e-12:
                raise ValueError("seed expected denominator lies below numerical floor")
        except (ValueError,OverflowError) as error:
            refused.append({"origin":origin,"coordinates":x.tolist() if np.all(np.isfinite(x)) else None,"error":str(error)})
            return False
        for old in starts:
            separation=float(np.max(np.abs(x-old)/np.maximum(1.,np.maximum(np.abs(x),np.abs(old)))))
            if separation<START_SEPARATION:
                return False
        starts.append(x)
        return True
    append(init,"source_initial")
    if document["mc_design"]["kind"]=="poisson_groups":
        for factor in (.7,1.3,.9,1.1):
            candidate=init.copy();candidate[offset:]*=factor
            if free_mu:
                candidate[0]=(.2 if factor<1 else 3)*init[0]
            append(candidate,"scaled_positive_rate")
            if len(starts)>=3:
                break
    else:
        scale=np.max(np.abs(W),axis=1)
        normalized=W/np.where(scale>0,scale,1)[:,None]
        d=np.asarray([c["denominator_mark"] for c in classes]);d_scale=float(np.max(np.abs(d)))
        matrix=np.vstack([-normalized,-d/d_scale]);rhs=np.r_[np.zeros(len(W)),-1e-12/d_scale]
        for coordinate in range(len(classes)):
            for sign in (1.,-1.):
                objective=np.zeros(len(classes));objective[coordinate]=sign
                try:
                    target=linprog(objective,A_ub=matrix,b_ub=rhs,A_eq=np.ones((1,len(classes))),b_eq=[1.],bounds=bounds[offset:],method="highs")
                    lp_attempts.append({"coordinate":coordinate,"objective_sign":sign,"success":bool(target.success),"message":str(target.message),
                                        "target_coordinates":target.x.tolist() if target.success and np.all(np.isfinite(target.x)) else None})
                    if not target.success or not np.all(np.isfinite(target.x)):
                        refused.append({"origin":"simplex_feasibility_LP","coordinate":coordinate,"sign":sign,"error":str(target.message)})
                        continue
                    for fraction in (.2,.35):
                        candidate=init.copy();candidate[offset:]=(1-fraction)*init[offset:]+fraction*target.x
                        if free_mu:
                            candidate[0]=(.2 if sign>0 else min(3.,.8*document["mu"]["upper"]/init[0]))*init[0]
                        append(candidate,"simplex_feasible_convex_mixture")
                        if len(starts)>=3:
                            break
                except Exception as error:
                    lp_attempts.append({"coordinate":coordinate,"objective_sign":sign,"success":False,"exception_type":type(error).__name__,"error":str(error)})
                    refused.append({"origin":"simplex_feasibility_LP","coordinate":coordinate,"sign":sign,"exception_type":type(error).__name__,"error":str(error)})
                if len(starts)>=3:
                    break
            if len(starts)>=3:
                break
    return starts,{"distinct_seed_count":len(starts),"normalized_minimum_separation":START_SEPARATION,
                   "method":"Feasible rate scaling or simplex linear-program targets with convex mixing; no likelihood/global-optimum certificate",
                   "actual_start_coordinates":[x.tolist() for x in starts],"refused_seed_candidates":refused,
                   "simplex_feasibility_LP_calls":len(lp_attempts),"simplex_feasibility_LP_attempts":lp_attempts}



def _diagnostic_values(value):
    """JSON-safe returned numerical evidence; null marks unavailable/nonfinite."""
    if hasattr(value, "tolist"):
        value = value.tolist()
    if isinstance(value, dict):
        return {key: _diagnostic_values(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_diagnostic_values(item) for item in value]
    return None if isinstance(value, float) and not math.isfinite(value) else value


def _tangent_active(residual, tolerance, *, physical):
    """Only exact evaluated physical zero can remove a tangent direction.

    Positive physical slack remains interior, regardless of its size.
    Numerical near-boundaries remain conservative refusal diagnostics.
    No coordinate or expectation is snapped/clipped by this predicate.
    """
    if not math.isfinite(float(residual)):
        raise ValueError("nonfinite tangent constraint residual")
    if physical and residual < 0:
        raise ValueError("negative physical tangent constraint residual")
    return bool(residual == 0 if physical else residual <= tolerance)


def fit(document,fixed_mu=None,data=None,maxiter=500):
    """Constrained multi-start profile, with tangent-cone LP stationarity.

    Fixed-mu Poisson-group objectives are convex. Ratio-normalized categorical
    and free-mu objectives can be nonconvex: multi-start agreement is retained
    as bounded numerical evidence, never claimed as global optimality proof.
    """
    import numpy as np
    import warnings
    from scipy.optimize import minimize,linprog
    document=prepare(document)
    if type(maxiter) is not int or not 20<=maxiter<=2000:
        raise ValueError("maxiter exceeds bounded fit ceiling")
    if fixed_mu is not None and not 0<=_number(fixed_mu,"fixed mu")<=document["mu"]["upper"]:
        raise ValueError("fixed mu out of bounds")
    _,m=_data(document,data)
    limits=structural_limits(document,data)
    if fixed_mu is None and limits["finite_mu_endpoint_not_established"]:
        return {"verified":False,"fixed_mu":None,"attempts":[],"structural_limits":limits,
                "failure":"all selected MC categories observed zero: unbounded/unidentified strength direction; no finite upper endpoint certified"}
    kind=document["mc_design"]["kind"]
    free_mu=fixed_mu is None
    offset=int(free_mu)
    classes=document["classes"]
    W=np.asarray([c["contribution"] for c in classes]).T
    floor=1e-12
    bounds=([(0.,document["mu"]["upper"])] if free_mu else [])+[(floor if count>0 else 0.,c["upper"]) for c,count in zip(classes,m)]
    init=np.asarray(([document["mu"]["initial"]] if free_mu else [])+[c["initial"] for c in classes])
    def point(x):
        return {"mu":float(x[0]) if free_mu else fixed_mu,"nuisance":{c["id"]:float(v) for c,v in zip(classes,x[offset:])}}
    def objective(x):
        try:
            result=evaluate(document,point(x),data)
            return result["nll"] if result["finite"] else math.inf,np.asarray(result["gradient"] if free_mu else result["gradient"][1:])
        except ValueError:
            # The optimizer may probe outside the linear feasible set. This
            # barrier applies to latent parameter support, not observed weights.
            return math.inf,np.zeros(len(x))
    constraints=[{"type":"ineq","fun":lambda x:W@x[offset:],"jac":lambda x:np.column_stack([np.zeros(len(W)),W]) if free_mu else W}]
    d=None
    if kind=="fixed_n_categories":
        d=np.asarray([c["denominator_mark"] for c in classes])
        constraints += [{"type":"eq","fun":lambda x:sum(x[offset:])-1.,"jac":lambda x:np.r_[0.,np.ones(len(classes))] if free_mu else np.ones(len(classes))},
                        {"type":"ineq","fun":lambda x:float(d@x[offset:])-floor,"jac":lambda x:np.r_[0.,d] if free_mu else d}]
    starts,start_generation=_distinct_feasible_starts(document,init,bounds,free_mu,fixed_mu,W,m)
    if len(starts)<2:
        return {"verified":False,"fixed_mu":fixed_mu,"attempts":[],"start_generation":start_generation,
                "failure":"fewer than two genuinely distinct feasible starts; degenerate support or numerical domain cannot certify multistart agreement"}
    attempts=[]
    for index,start in enumerate(starts):
        caught=[]
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result=minimize(objective,start.copy(),jac=True,bounds=bounds,constraints=constraints,method="SLSQP",options={"maxiter":maxiter,"ftol":1e-12})
        except Exception as error:
            # Retain a bounded solver failure without turning it into missing
            # ensemble data. Interrupts and process exits still propagate.
            attempts.append({"start":index,"method":"SLSQP","success":False,"verified":False,
                             "start_coordinates":start.tolist(),"start_parameters":point(start),
                             "failure_kind":"optimizer_exception","exception_type":type(error).__name__,"error":str(error),
                             "optimizer_warnings":[{"category":w.category.__name__,"message":str(w.message)} for w in caught]})
            continue
        optimizer_warnings=[{"category":w.category.__name__,"message":str(w.message)} for w in caught]
        x=result.x
        witness={"coordinate_order":(["mu"] if free_mu else [])+["MC:"+c["id"] for c in classes],
                 "coordinates":_diagnostic_values(x),
                 "activity_rule":"literal_zero_physical_slack; negative_physical_slack_refuses; numerical_proximity_conservative_refusal",
                 "gradient_tolerance":1e-4,"nonfinite_diagnostic_values":"represented_by_null; never_admitted_as_finite"}
        try:
            if np.shape(x)!=(len(bounds),):
                raise ValueError("optimizer returned coordinate population differs from declared fit")
            witness.update({"coordinate_bounds":_diagnostic_values(bounds),
                 "coordinate_slacks":_diagnostic_values([[v-lo,hi-v] for v,(lo,hi) in zip(x,bounds)]),
                 "bound_semantics":[["physical" if (free_mu and i==0 or i>=offset and lo==0) else "numerical",
                                     "physical" if i>=offset and kind=="fixed_n_categories" else "numerical"] for i,(lo,hi) in enumerate(bounds)],
                 "linear_constraints":{"net_matrix":_diagnostic_values(np.column_stack((np.zeros(len(W)),W)) if free_mu else W),
                    "net_residuals":_diagnostic_values(W@x[offset:]),"net_bins":[b["id"] for b in document["bins"]],
                    "denominator_row":_diagnostic_values(np.r_[0.,d] if free_mu else d) if d is not None else None,
                    "denominator_floor":floor if d is not None else None,
                    "denominator_residual":_diagnostic_values(float(d@x[offset:])-floor) if d is not None else None,
                    "simplex_residual":_diagnostic_values(float(np.sum(x[offset:]))-1.) if kind=="fixed_n_categories" else None}})
            physical=point(x);evaluated=evaluate(document,physical,data)
            if not evaluated["finite"]:
                raise ValueError("optimizer returned a zero-probability point")
            gradient=np.asarray(evaluated["gradient"] if free_mu else evaluated["gradient"][1:])
            witness["raw_coordinate_gradient"]=_diagnostic_values(gradient)
            active=[];directions=[]
            for i,(lo,hi) in enumerate(bounds):
                scale=max(1.,abs(float(x[i])))
                lower_physical=bool(free_mu and i==0 or i>=offset and lo==0)
                upper_physical=bool(i>=offset and kind=="fixed_n_categories")
                at_lo=_tangent_active(float(x[i])-lo,1e-7,physical=lower_physical)
                at_hi=_tangent_active(hi-float(x[i]),1e-7,physical=upper_physical)
                directions.append((0. if at_lo else -scale,0. if at_hi else scale))
                if at_lo:
                    active.append({"coordinate":i,"side":"lower","physical":lower_physical})
                if at_hi:
                    active.append({"coordinate":i,"side":"upper","physical":upper_physical})
            linear=[]
            for w,value in zip(W,W@x[offset:]):
                if _tangent_active(float(value),1e-7,physical=True):
                    linear.append(-(np.r_[0.,w] if free_mu else w))
            if d is not None and _tangent_active(float(d@x[offset:])-floor,1e-7,physical=False):
                linear.append(-(np.r_[0.,d] if free_mu else d))
                active.append({"coordinate":"expected_denominator_floor","side":"lower","physical":False})
            equality=(np.r_[0.,np.ones(len(classes))] if free_mu else np.ones(len(classes)))[None,:] if kind=="fixed_n_categories" else None
            witness["lp"]={"objective":_diagnostic_values(gradient),"direction_bounds":_diagnostic_values(directions),
                "A_ub":_diagnostic_values(linear) if linear else None,"b_ub":[0.]*len(linear) if linear else None,
                "A_eq":_diagnostic_values(equality),"b_eq":[0.] if equality is not None else None,"active_constraints":deepcopy(active)}
            stationarity=linprog(gradient,A_ub=np.asarray(linear) if linear else None,b_ub=np.zeros(len(linear)) if linear else None,A_eq=equality,b_eq=[0.] if equality is not None else None,bounds=directions,method="highs")
            witness["lp"]["result"]={"success":bool(stationarity.success),"message":str(stationarity.message),
                "direction":_diagnostic_values(getattr(stationarity,"x",None)),"objective":_diagnostic_values(getattr(stationarity,"fun",None))}
            violation=max(0.,-float(stationarity.fun)) if stationarity.success and math.isfinite(float(stationarity.fun)) else None
            independent=independent_density(document,physical,data)
            if not independent["finite"]:
                raise ValueError("independent density rejects optimizer point")
            identified=identifiability(document,physical)
            verified=bool(result.success and violation is not None and violation<=1e-4 and identified["identified"] and all(a["physical"] for a in active) and abs(evaluated["nll"]-independent["nll"])<=1e-8)
            attempts.append({"start":index,"method":"SLSQP","success":bool(result.success),"verified":verified,"message":str(result.message),"iterations":int(result.nit),"optimizer_warnings":optimizer_warnings,
                             "start_coordinates":start.tolist(),"start_parameters":point(start),
                             "stationarity_witness":witness,"parameters":physical,"nll":evaluated["nll"],"tangent_descent_violation":violation,"active_bounds":active,
                             "stationarity_solver_success":bool(stationarity.success),"stationarity_solver_message":str(stationarity.message),
                             "active_net_expectation_bins":[document["bins"][i]["id"] for i,v in enumerate(evaluated["raw_mark_expectation"]) if v==0],
                             "near_net_expectation_bins":[document["bins"][i]["id"] for i,v in enumerate(evaluated["raw_mark_expectation"]) if 0<v<=1e-7],
                             "identifiability":identified,"independent_nll_difference":abs(evaluated["nll"]-independent["nll"])})
        except Exception as error:
            attempts.append({"start":index,"success":bool(result.success),"verified":False,"failure_kind":"verification_exception",
                             "start_coordinates":start.tolist(),"start_parameters":point(start),
                             "stationarity_witness":witness,"exception_type":type(error).__name__,"error":str(error),"optimizer_warnings":optimizer_warnings})
    candidates=[r for r in attempts if r["verified"]]
    if len(candidates)<2:
        return {"verified":False,"fixed_mu":fixed_mu,"attempts":attempts,"start_generation":start_generation,
                "failure":"fewer than two distinct feasible identified stationary starts; artificial caps are unresolved"}
    best=min(candidates,key=lambda r:r["nll"])
    gap=max(r["nll"] for r in candidates)-best["nll"]
    return {"verified":gap<=1e-5,"fixed_mu":fixed_mu,"parameters":best["parameters"],"nll":best["nll"],"attempts":attempts,"start_generation":start_generation,"multi_start_nll_spread":gap,
            "conditional_convex":kind=="poisson_groups" and fixed_mu is not None,
            "limits":"One constrained solver with distinct starts and tangent-cone checks; free-mu and ratio cases have no global-optimum certificate."}


def profile(document,strengths=None,data=None,maxiter=500):
    best=fit(document,data=data,maxiter=maxiter)
    rows=[]
    for mu in document["profile_points"] if strengths is None else strengths:
        conditional=fit(document,mu,data,maxiter)
        statistic=None
        if best["verified"] and conditional["verified"]:
            delta=2*(conditional["nll"]-best["nll"])
            if delta>=-1e-5:
                statistic=max(0.,delta)
            else:
                conditional["verified"]=False
                conditional["failure"]="conditional fit improves claimed free minimum"
        rows.append({"mu":mu,"fit":conditional,"twice_delta_nll":statistic})
    return {"verified":bool(best["verified"] and all(r["fit"]["verified"] and r["twice_delta_nll"] is not None for r in rows)),"global_fit":best,"profiles":rows}


def draw_data(document,truth,rng):
    """Repeat both measurements; never substitute observed MC as truth."""
    _point(document,truth)
    means=evaluate(document,truth)["main_means"]
    values=[truth["nuisance"][c["id"]] for c in document["classes"]]
    main=rng.poisson(means).tolist()
    if document["mc_design"]["kind"]=="poisson_groups":
        mc=rng.poisson([c["exposure"]*v for c,v in zip(document["classes"],values)]).tolist()
    else:
        mc=rng.multinomial(document["mc_design"]["total_groups"],values).tolist()
    return {"main":main,"mc":mc}


def calibrate(document):
    import numpy as np
    from scipy.stats import beta
    document=prepare(document);protocol=document["calibration"]
    if not protocol["enabled"]:
        return {"executed":False,"protocol":deepcopy(protocol)}
    rng=np.random.default_rng(protocol["seed"]);ensembles=[]
    for truth in protocol["truths"]:
        trials=[]
        for index in range(protocol["trials_per_truth"]):
            try:
                data=draw_data(document,truth,rng)
            except Exception as error:
                trials.append({"index":index,"data":None,"fit":{"verified":False,"failure_kind":"sampling_exception",
                               "exception_type":type(error).__name__,"error":str(error)},"verified":False,"includes_truth":None})
                continue
            try:
                result=profile(document,[truth["mu"]],data,protocol["maxiter"])
            except Exception as error:
                # Data already drawn at the frozen truth remain an actual
                # failed trial. Never redraw or reduce the denominator.
                result={"verified":False,"failure_kind":"profile_exception","exception_type":type(error).__name__,"error":str(error)}
            statistic=result["profiles"][0]["twice_delta_nll"] if result["verified"] else None
            trials.append({"index":index,"data":data,"fit":result,"verified":result["verified"],"includes_truth":bool(statistic<=protocol["threshold"]) if statistic is not None else None})
        total=len(trials);resolved=[r for r in trials if r["verified"]];successes=sum(r["includes_truth"] for r in resolved);failures=total-len(resolved)
        def interval(s):
            alpha=(1-protocol["confidence_level"])/2
            return [float(beta.ppf(alpha,s,total-s+1)) if s else 0.,float(beta.ppf(1-alpha,s+1,total-s)) if s<total else 1.]
        estimates=[r["fit"]["global_fit"]["parameters"]["mu"] for r in resolved]
        ensembles.append({"truth":truth,"generated":sum(r["data"] is not None for r in trials),"attempted":total,"denominator":total,
                          "resolved":len(resolved),"failed":failures,"coverage_bounds_all_trials":[successes/total,(successes+failures)/total],
                          "binomial_intervals_failure_exclude_include":[interval(successes),interval(successes+failures)],"coverage_mcse_upper_bound":.5/math.sqrt(total),
                          "mu_bias_resolved_only":float(np.mean(estimates)-truth["mu"]) if estimates else None,"trials":trials})
    return {"executed":True,"protocol":deepcopy(protocol),"ensembles":ensembles,"all_fits_resolved":all(e["failed"]==0 for e in ensembles),
            "limits":["All failures stay in denominator; finite-toy precision is explicit.","Threshold confidence-set inclusion is not CLs or calibrated endpoint inversion.",
                      "Both main and MC auxiliaries repeat at fixed nuisance truth; no prior draws.","Exact family assumes known fixed marks/support/design/exposure; native sampling-law validity remains a source obligation."]}


def signed_law_witness(tail=1e-13):
    """A=Pois(4)-Pois(2), B=2Pois(4/3)-Pois(2/3): same mean/variance.

    Return exact discrete-law convolutions with an explicit omitted-tail bound.
    These are truth-law moments, not fabricated fractional observed MC counts.
    """
    from scipy.stats import poisson,skellam
    laws=[]
    for name,positive,negative,weight in (("A",4.,2.,1),("B",4/3,2/3,2)):
        hi_p=int(poisson.ppf(1-tail/2,positive));hi_n=int(poisson.ppf(1-tail/2,negative))
        mass={}
        for p in range(hi_p+1):
            for n in range(hi_n+1):
                value=weight*p-n
                mass[value]=mass.get(value,0.)+float(poisson.pmf(p,positive)*poisson.pmf(n,negative))
        laws.append({"name":name,"positive_rate":positive,"negative_rate":negative,"positive_weight":weight,"mean":weight*positive-negative,
                     "variance":weight**2*positive+negative,"third_cumulant":weight**3*positive-negative,"pmf":{str(k):v for k,v in sorted(mass.items())},
                     "omitted_tail_bound":float(poisson.sf(hi_p,positive)+poisson.sf(hi_n,negative))})
    keys=set(laws[0]["pmf"])|set(laws[1]["pmf"])
    return {"laws":laws,"pmf_L1_distance":sum(abs(laws[0]["pmf"].get(k,0.)-laws[1]["pmf"].get(k,0.)) for k in keys),
            "A_skellam_zero_residual":abs(laws[0]["pmf"]["0"]-float(skellam.pmf(0,4.,2.))),
            "consequence":"sumw/sumw2 or mean/covariance alone do not specify a signed MC likelihood"}


def _admit_output(output_dir):
    out=Path(output_dir).absolute()
    if any(p.is_symlink() for p in (out,*out.parents)):
        raise ValueError("finite MC output must not traverse a symlink")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError("finite MC requires a new or empty output directory")
    out.mkdir(parents=True,exist_ok=True)
    return out


def run(task,base_dir,output_dir):
    # Admit the artifact destination before reading inputs or running a fit.
    out=_admit_output(output_dir)
    document,captured=_capture(task,base_dir)
    comparisons=[]
    for point in document["comparison_points"]:
        try:
            analytic=evaluate(document,point);independent=independent_density(document,point)
            passed=analytic["finite"] and independent["finite"] and abs(analytic["nll"]-independent["nll"])<=1e-8
            comparisons.append({"parameters":point,"analytic":analytic,"independent":independent,"passed":bool(passed)})
        except Exception as error:
            comparisons.append({"parameters":point,"passed":False,"failure_kind":"comparison_exception",
                                "exception_type":type(error).__name__,"error":str(error)})
    fitted=profile(document,maxiter=document["calibration"]["maxiter"]) if all(r["passed"] for r in comparisons) else None
    calibration=calibrate(document) if fitted and fitted["verified"] else {"executed":False,"reason":"unresolved arithmetic/profile"}
    result={"schema_version":1,"kind":"source_bound_fixed_mark_finite_MC","model_id":document["model_id"],"physics_validated":False,
            "status":"passed" if fitted and fitted["verified"] and (not calibration["executed"] or calibration["all_fits_resolved"]) else "failed",
            "mc_law":document["mc_design"],"comparisons":comparisons,"profile":fitted,"calibration":calibration,
            "resource_bounds":_resource_bounds(document),
            "inputs":[{"path":p,"sha256":hashlib.sha256(raw).hexdigest()} for p,raw in captured.items()],
            "limits":["Staged restricted likelihood; native generator adequacy and calibration quality remain unestablished.","Fixed positive background is conditional supplied input; no background-systematic or detector closure claim."]}
    for p,raw in captured.items():
        if Path(p).read_bytes()!=raw:
            raise ValueError("source changed during finite MC execution")
    serialized=[("finite_mc_"+name+".json",json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+"\n")
                for name,value in (("contract",document),("result",result),("profile",fitted),("calibration",calibration))]
    if any(out.iterdir()):
        raise FileExistsError("finite MC output changed after admission")
    for name,value in serialized:
        with (out/name).open("x") as handle:
            handle.write(value)
    return result
