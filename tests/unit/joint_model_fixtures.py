"""Small complete synthetic ledgers; no historical inputs or external assets."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path


def compact(value):return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def parts(kind):
    signed=kind=="fixed-N-signed";poisson=kind=="poisson-A"
    if poisson:spec=[([1.,.5],None,4,4.),([-1.,-.5],None,2,2.)]
    elif signed:spec=[([1.,.2],1.,4,.4),([-1.,-.2],-1.,1,.1),([0.,0.],1.,4,.4),([0.,0.],-1.,1,.1)]
    else:spec=[([1.,0.],1.,3,.3),([0.,1.],1.,3,.3),([0.,0.],1.,4,.4)]
    classes=[];groups=[]
    for i,(marks,denominator,n,initial) in enumerate(spec):
        ids=[f"group{i}-{j}" for j in range(n)]
        classes.append({"id":f"class{i}","contribution":marks,"denominator_mark":denominator,"exposure":1. if poisson else None,"observed":n,"observed_group_ids":ids,"initial":initial,"source":"ledger"})
        groups.extend({"id":identity,"class_id":f"class{i}","contribution":list(marks),"denominator_mark":denominator} for identity in ids)
    bins=[{"id":"SR","role":"signal","source":"ledger"},{"id":"CR","role":"control","source":"ledger"}]
    design={"kind":"poisson_groups" if poisson else "fixed_n_categories","sampling_law":"independent_poisson_fixed_mark_populations" if poisson else "iid_fixed_mark_categories","fixed_marks":True,"support_complete":True,"ledger_source":"ledger","independence":"disjoint_poisson_group_populations" if poisson else "iid_groups_within_one_fixed_N_stream","total_groups":None if poisson else 10,"kappa":None if poisson else 20.,"normalization_source":"ledger","normalization_meaning":"Explicit synthetic known exposure or inclusive normalization"}
    ledger={"schema_version":1,"sampling_law":design["sampling_law"],"support_complete":True,"classes":[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in classes],"groups":groups,"normalization":{key:design[key] for key in ("total_groups","kappa","normalization_meaning")},"bins":[{key:b[key] for key in ("id","role")} for b in bins]}
    return bins,classes,design,ledger


def write_mc(directory,kind="fixed-N-LO"):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    bins,classes,design,ledger=parts(kind);raw=compact(ledger);(directory/"mc-ledger.json").write_bytes(raw)
    source={"id":"ledger","path":"mc-ledger.json","sha256":hashlib.sha256(raw).hexdigest(),"reference":"Explicit complete synthetic fixed-mark sampling law; developer control only"}
    document={"schema_version":1,"model_id":"synthetic-MC-only","sources":[source],"bins":bins,"mc_design":design,"classes":classes,"assumptions":["Known fixed marks and complete support supplied explicitly.","Poisson populations or IID complete fixed-N categories are mathematical test assumptions, not a native generator claim."]}
    path=directory/"mc-model.json";path.write_bytes(compact(document));return path


def write_legacy(directory,kind="fixed-N-LO"):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    bins,classes,design,ledger=parts(kind)
    for i,b in enumerate(bins):b.update(observed=8+2*i,background=2.+2*i,observation_id="observed-"+b["id"])
    for c in classes:c["upper"]=100. if design["kind"]=="poisson_groups" else 1.
    partition={"kind":"disjoint","source":"ledger","overlap_counts":[[8,0],[0,10]]}
    ledger.pop("bins");ledger["main_bins"]=[{key:b[key] for key in ("id","role","observed","background","observation_id")} for b in bins]
    ledger["main_partition"]={key:partition[key] for key in ("kind","overlap_counts")}
    raw=compact(ledger);(directory/"ledger.json").write_bytes(raw)
    source={"id":"ledger","path":"ledger.json","sha256":hashlib.sha256(raw).hexdigest(),"reference":"Complete synthetic historical wrapper fixture; no external inputs"}
    point={"mu":1.,"nuisance":{c["id"]:c["initial"] for c in classes}}
    other=deepcopy(point);other["mu"]=2.
    document={"schema_version":1,"model_id":"synthetic-historical","sources":[source],"bins":bins,"partition":partition,"background_contract":{"mode":"conditional_fixed","source":"ledger","meaning":"Synthetic conditional background for importer regression only"},"mc_design":design,"classes":classes,"mu":{"initial":.8,"upper":30.,"meaning":"Complete source signal strength"},"comparison_points":[point,other],"profile_points":[1.,2.],"calibration":{"enabled":False,"seed":4991,"trials_per_truth":1,"truths":[point],"nuisance_sampling":"fixed_truth","main_sampling":"repeat_poisson_main","mc_sampling":"repeat_declared_MC_law","threshold":3.841458820694124,"confidence_level":.95,"maxiter":150},"assumptions":["Explicit known fixed marks and complete support.","Known sampling design supplied as a synthetic mathematical law.","Conditional main fixture is for import checks only."]}
    path=directory/"model.json";path.write_bytes(compact(document));return path
