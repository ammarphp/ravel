"""Standalone source-bound MC auxiliary, with no main measurement fields.

Exact likelihoods are conditional on supplied complete fixed-mark IID or
Poisson-group laws. Extraction validates the historical wrapper once, then
emits a genuinely separate ledger/schema; evaluation never fabricates a main
background or main observation to call the earlier likelihood.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType

from ravel.physics import finite_mc_model as fm
from ravel.physics.quantities import _keys,_number,_text

def compact(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


MAX_BYTES=8*1024**2
MAX_TOTAL_BYTES=32*1024**2
MAX_SOURCES=16


def _read(path):
    """Bound before allocation and bound the read again against file growth."""
    if path.stat().st_size>MAX_BYTES:raise ValueError("MC input exceeds 8 MiB")
    with path.open("rb") as stream:raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError("MC input exceeds 8 MiB")
    return raw


def _legacy_capture(task,base):
    """Bounded historical importer, validating rather than reusing its main law."""
    fm.validate(task);path=fm._regular(task["input"],base);raw=_read(path)
    decoded=fm._load_bytes(raw)
    if not isinstance(decoded,dict) or not isinstance(decoded.get("sources"),list) or not 1<=len(decoded["sources"])<=MAX_SOURCES-2:raise ValueError("bounded legacy source inventory required")
    document=fm.prepare(decoded);captured={str(path):raw};sources={}
    for pin in document["sources"]:
        source=fm._regular(pin["path"],path.parent);data=_read(source)
        if hashlib.sha256(data).hexdigest()!=pin["sha256"]:raise ValueError("legacy MC source hash differs")
        captured[str(source)]=data;sources[pin["id"]]=data
        if sum(map(len,captured.values()))>MAX_TOTAL_BYTES:raise ValueError("legacy capture exceeds aggregate byte ceiling")
    ledger=fm._load_bytes(sources[document["mc_design"]["ledger_source"]])
    _keys(ledger,("schema_version","sampling_law","support_complete","classes","groups","normalization","main_bins","main_partition"),label="historical ledger")
    expected=[{key:b[key] for key in ("id","role","observed","background","observation_id")} for b in document["bins"]]
    if ledger["main_bins"]!=expected or ledger["main_partition"]!={key:document["partition"][key] for key in ("kind","overlap_counts")}:raise ValueError("historical main provenance differs")
    for name,data in captured.items():
        if _read(fm._regular(name,Path.cwd()))!=data:raise ValueError("legacy input changed during bounded capture")
    return document,captured


def extract_legacy_mc(task,base,destination,*,model_id):
    """One-time export; preserve historical source identity without its main law."""
    _text(model_id,"MC-only model identity")
    output=Path(destination)
    if output.exists() or output.is_symlink():
        raise ValueError("MC-only export requires a new output directory")
    old,captured=_legacy_capture(task,base)
    original=fm._regular(task["input"],base)
    ledger_pin=next(p for p in old["sources"] if p["id"]==old["mc_design"]["ledger_source"])
    ledger=fm._load_bytes(captured[str(fm._regular(ledger_pin["path"],original.parent))])
    clean={key:deepcopy(ledger[key]) for key in ("schema_version","sampling_law","support_complete","classes","groups","normalization")}
    clean["bins"]=[{key:b[key] for key in ("id","role")} for b in old["bins"]]
    raw=compact(clean)
    sources=[]
    for pin in old["sources"]:
        row=deepcopy(pin);row["path"]=str(fm._regular(row["path"],original.parent));sources.append(row)
    if any(p["id"] in {"mc-only-ledger","legacy-wrapper"} for p in sources):
        raise ValueError("reserved extraction source identity collision")
    sources.extend([{"id":"mc-only-ledger","path":"mc-ledger.json","sha256":hashlib.sha256(raw).hexdigest(),"reference":"Complete MC-only fixed-mark support/group export"},
                    {"id":"legacy-wrapper","path":str(original),"sha256":hashlib.sha256(captured[str(original)]).hexdigest(),"reference":"Extraction provenance only; conditional main experiment retired"}])
    design=deepcopy(old["mc_design"]);design["ledger_source"]="mc-only-ledger"
    document={"schema_version":1,"model_id":model_id,"sources":sources,"bins":[{key:b[key] for key in ("id","role","source")} for b in old["bins"]],
              "mc_design":design,"classes":[{key:value for key,value in deepcopy(c).items() if key!="upper"} for c in old["classes"]],"assumptions":old["assumptions"][:2]+["The historical main measurement/background are provenance only and do not enter this MC auxiliary likelihood."]}
    prepare(document);_ledger(document,clean)
    if len(compact(document))>MAX_BYTES or len(raw)>MAX_BYTES:raise ValueError("export exceeds bounded file size")
    if sum(map(len,captured.values()))+len(raw)+len(compact(document))>MAX_TOTAL_BYTES:raise ValueError("export exceeds aggregate input byte ceiling")
    output.mkdir(parents=True);(output/"mc-ledger.json").write_bytes(raw)
    (output/"mc-model.json").write_bytes(compact(document))
    (output/"legacy-search-recommendations.json").write_bytes(compact({"scope":"Numerical search metadata only; absent from MC density support","mu":old["mu"],"rate_caps":{c["id"]:c["upper"] for c in old["classes"]} if design["kind"]=="poisson_groups" else {}}))
    # Captured sources must still match after export; no input is overwritten.
    for path,data in captured.items():
        if _read(fm._regular(path,Path.cwd()))!=data:
            raise ValueError("legacy source changed during MC-only extraction")
    return output/"mc-model.json"


def prepare(document):
    _keys(document,("schema_version","model_id","sources","bins","mc_design","classes","assumptions"),label="MC-only model")
    if type(document["schema_version"]) is not int or document["schema_version"] not in (1, 2):
        raise ValueError("unsupported MC-only schema")
    _text(document["model_id"],"MC model identity")
    if not isinstance(document["sources"],list) or not 1<=len(document["sources"])<=MAX_SOURCES:
        raise ValueError("MC source pins required")
    for pin in document["sources"]:
        _keys(pin,("id","path","sha256","reference"),label="MC source pin")
        for key in ("id","path","reference"):_text(pin[key],key)
        if not isinstance(pin["sha256"],str) or len(pin["sha256"])!=64 or any(c not in "0123456789abcdef" for c in pin["sha256"]):
            raise ValueError("invalid source SHA256")
    ids=[p["id"] for p in document["sources"]];fm._ids(ids,"source ids")
    bins=document["bins"]
    generalized = document["schema_version"] == 2
    if not isinstance(bins,list) or not (1 if generalized else 2)<=len(bins)<=(64 if generalized else 8):
        raise ValueError("explicit MC target-bin population exceeds schema resource admission")
    for row in bins:
        _keys(row,("id","role","source"),label="MC target bin")
        _text(row["id"],"bin id")
        if row["role"] not in {"signal","control"} or row["source"] not in ids:raise ValueError("source-bound SR/CR target required")
    fm._ids([b["id"] for b in bins],"bin ids")
    if not generalized and {b["role"] for b in bins}!={"signal","control"}:raise ValueError("full SR and CR support required")
    design=document["mc_design"]
    _keys(design,("kind","sampling_law","fixed_marks","support_complete","ledger_source","independence","total_groups","kappa","normalization_source","normalization_meaning"),label="MC design")
    if design["fixed_marks"] is not True or design["support_complete"] is not True or design["ledger_source"] not in ids or design["normalization_source"] not in ids:
        raise ValueError("complete source-bound fixed-mark sampling law required")
    _text(design["normalization_meaning"],"normalization meaning")
    if design["kind"]=="poisson_groups":
        if design["sampling_law"]!="independent_poisson_fixed_mark_populations" or design["independence"]!="disjoint_poisson_group_populations" or design["total_groups"] is not None or design["kappa"] is not None:
            raise ValueError("Poissonization needs an actual declared Poisson group law")
    elif design["kind"]=="fixed_n_categories":
        if design["sampling_law"]!="iid_fixed_mark_categories" or design["independence"]!="iid_groups_within_one_fixed_N_stream" or type(design["total_groups"]) is not int or not 1<=design["total_groups"] or (not generalized and design["total_groups"]>100000) or not 0<_number(design["kappa"],"kappa") or (not generalized and design["kappa"]>1e6):
            raise ValueError("exact fixed-N law needs complete IID category support and known kappa")
    else:raise ValueError("sumw/sumw2 do not specify an MC sampling law")
    classes=document["classes"]
    if not isinstance(classes,list) or not 2<=len(classes)<=(64 if generalized else 8):raise ValueError("complete MC classes exceed schema resource admission")
    if generalized and len(classes)*len(bins)>4096:raise ValueError("complete category-mark matrix exceeds resource admission")
    group_ids=[]
    for c in classes:
        _keys(c,("id","contribution","denominator_mark","exposure","observed","observed_group_ids","initial","source"),label="MC class")
        _text(c["id"],"class id");fm._numbers(c["contribution"],len(bins),"fixed marks")
        if c["source"] not in ids or type(c["observed"]) is not int or c["observed"]<0:raise ValueError("nonnegative integer group observations required")
        fm._ids(c["observed_group_ids"],"group identities",empty=True)
        if len(c["observed_group_ids"])!=c["observed"]:raise ValueError("complete observed group identities required")
        group_ids+=c["observed_group_ids"]
        initial=_number(c["initial"],"initial")
        if design["kind"]=="poisson_groups":
            if c["denominator_mark"] is not None or not 0<_number(c["exposure"],"exposure")<=1e6 or not 0<initial:raise ValueError("known Poisson exposure and positive interior start required")
        elif c["exposure"] is not None or not 0<initial<1:
            raise ValueError("complete physical probability simplex required")
        else:_number(c["denominator_mark"],"fixed denominator mark")
    fm._ids([c["id"] for c in classes],"classes");fm._ids(group_ids,"globally unique group ids",empty=True)
    if design["kind"]=="fixed_n_categories" and (len(classes)<2 or sum(c["observed"] for c in classes)!=design["total_groups"] or abs(sum(c["initial"] for c in classes)-1)>1e-12):raise ValueError("fixed N must include every unselected category")
    if not generalized and any(not any(c["contribution"][i] for c in classes) for i in range(len(bins))):raise ValueError("each target bin needs declared signal support")
    # Schema2 retains every zero-reference bin. A response provider must bind
    # any proposed nonzero variation marks; this auxiliary creates none.
    if not isinstance(document["assumptions"],list) or len(document["assumptions"])<2:raise ValueError("explicit generator assumptions required")
    for text in document["assumptions"]:_text(text,"assumption")
    _physical(document,{c["id"]:c["initial"] for c in classes})
    return deepcopy(document)


def _physical(document,latent):
    """Physical latent domain only; finite numerical rate caps are absent."""
    _keys(latent,[c["id"] for c in document["classes"]],label="complete MC latent point")
    values=[_number(latent[c["id"]],"latent rate/probability") for c in document["classes"]]
    fixed=document["mc_design"]["kind"]=="fixed_n_categories"
    if any(v<0 or fixed and v>1 for v in values):raise ValueError("negative rate or probability outside physical simplex")
    if fixed and abs(math.fsum(values)-1)>1e-12:raise ValueError("complete physical probability simplex required")
    try:
        raw=[math.fsum(c["contribution"][i]*v for c,v in zip(document["classes"],values)) for i in range(len(document["bins"]))]
        denominator=math.fsum(c["denominator_mark"]*v for c,v in zip(document["classes"],values)) if fixed else None
    except (OverflowError,ValueError) as error:raise ValueError("derived mark expectation overflow") from error
    if any(not math.isfinite(v) for v in raw) or any(v<0 for v in raw):raise ValueError("negative or nonfinite latent NET expectation; observed signed sums are not clamped")
    if fixed and (not math.isfinite(denominator) or denominator<=0):raise ValueError("strictly positive expected signed denominator required")
    return values,raw,denominator


def complete_auxiliary_means(document, latent):
    """MC experiment coordinates alone, without a reference signal constraint.

    The absolute response consumer checks its actual transported signal and
    denominator separately. This helper neither renormalizes probabilities
    nor evaluates a density or changes the legacy nominal-domain API.
    """
    _keys(latent,[c["id"] for c in document["classes"]],label="complete MC latent point")
    values=[_number(latent[c["id"]],"latent rate/probability") for c in document["classes"]]
    fixed=document["mc_design"]["kind"]=="fixed_n_categories"
    if any(v<0 or fixed and v>1 for v in values):raise ValueError("negative rate or probability outside physical simplex")
    if fixed and abs(math.fsum(values)-1)>1e-12:raise ValueError("complete physical probability simplex required")
    means=[document["mc_design"]["total_groups"]*v for v in values] if fixed else [c["exposure"]*v for c,v in zip(document["classes"],values)]
    if any(not math.isfinite(x) for x in means):raise ValueError("MC auxiliary expectation overflow")
    return {"mc_means":means}


def _ledger(document,ledger):
    _keys(ledger,("schema_version","sampling_law","support_complete","classes","groups","normalization","bins"),label="MC-only ledger")
    if not isinstance(ledger["classes"],list):raise ValueError("complete ledger classes required")
    for c in ledger["classes"]:
        _keys(c,("id","contribution","denominator_mark","exposure"),label="ledger class")
        _text(c["id"],"class id");fm._numbers(c["contribution"],len(document["bins"]),"ledger fixed marks")
        for key in ("denominator_mark","exposure"):
            if c[key] is not None:_number(c[key],"ledger "+key)
    _keys(ledger["normalization"],("total_groups","kappa","normalization_meaning"),label="ledger normalization")
    if ledger["normalization"]["total_groups"] is not None and type(ledger["normalization"]["total_groups"]) is not int:raise ValueError("ledger N must be a strict integer")
    if ledger["normalization"]["kappa"] is not None:_number(ledger["normalization"]["kappa"],"ledger kappa")
    expected=[{key:c[key] for key in ("id","contribution","denominator_mark","exposure")} for c in document["classes"]]
    design=document["mc_design"]
    if type(ledger["schema_version"]) is not int or ledger["schema_version"]!=1 or ledger["support_complete"] is not True or ledger["classes"]!=expected or ledger["sampling_law"]!=design["sampling_law"] or ledger["bins"]!=[{key:b[key] for key in ("id","role")} for b in document["bins"]] or ledger["normalization"]!={key:design[key] for key in ("total_groups","kappa","normalization_meaning")}:
        raise ValueError("complete MC-only ledger/support/normalization differs")
    observed={c["id"]:[] for c in document["classes"]}
    if not isinstance(ledger["groups"],list):raise ValueError("MC group ledger required")
    for group in ledger["groups"]:
        _keys(group,("id","class_id","contribution","denominator_mark"),label="group")
        fm._numbers(group["contribution"],len(document["bins"]),"observed fixed marks")
        if group["denominator_mark"] is not None:_number(group["denominator_mark"],"observed fixed denominator mark")
        if group["class_id"] not in observed:raise ValueError("unknown observed MC class")
        c=next(c for c in document["classes"] if c["id"]==group["class_id"])
        if group["contribution"]!=c["contribution"] or group["denominator_mark"]!=c["denominator_mark"]:raise ValueError("marks vary within a declared fixed-mark class")
        observed[c["id"]].append(group["id"])
    if any(observed[c["id"]]!=c["observed_group_ids"] for c in document["classes"]):raise ValueError("MC group identities/counts differ")


class MCAuxiliaryBlock:
    def __init__(self,task,base="."):
        fm.validate(task);path=fm._regular(task["input"],base);raw=_read(path)
        self._document=prepare(fm._load_bytes(raw));self._captured={str(path):raw};sources={}
        for pin in self._document["sources"]:
            p=fm._regular(pin["path"],path.parent);data=_read(p)
            if hashlib.sha256(data).hexdigest()!=pin["sha256"]:raise ValueError("MC-only source changed: "+pin["id"])
            self._captured[str(p)]=data;sources[pin["id"]]=data
            if sum(map(len,self._captured.values()))>MAX_TOTAL_BYTES:raise ValueError("MC capture exceeds aggregate byte ceiling")
        ledger=fm._load_bytes(sources[self._document["mc_design"]["ledger_source"]])
        _ledger(self._document,ledger)
        self._bins=tuple(b["id"] for b in self._document["bins"]);self._classes=tuple(c["id"] for c in self._document["classes"])
        self._indices=MappingProxyType({name:i for i,name in enumerate(self._bins)})
        self.assert_custody()

    @property
    def bin_ids(self):return list(self._bins)
    @property
    def class_ids(self):return list(self._classes)
    def bin_index(self,name):return self._indices[name]
    def document(self):return deepcopy(self._document)
    def contract(self):return {"schema":"MC-only-v2" if self._document["schema_version"] == 2 else "MC-only-v1","mc_model_sha256":hashlib.sha256(compact(self._document)).hexdigest(),"document":self.document(),"inputs":[{"path":p,"sha256":hashlib.sha256(raw).hexdigest()} for p,raw in self._captured.items()],"resource_admission":{"maximum_file_bytes":MAX_BYTES,"maximum_total_input_bytes":MAX_TOTAL_BYTES,"maximum_sources":MAX_SOURCES},"scope":"MC auxiliary and latent signal expectation only; no main experiment"}
    def assert_custody(self):
        for path,raw in self._captured.items():
            if _read(fm._regular(path,Path.cwd()))!=raw:raise ValueError("MC-only source changed")
    def counts(self,observations=None):
        values=[c["observed"] for c in self._document["classes"]] if observations is None else observations
        if not isinstance(values,list) or len(values)!=len(self._classes) or any(type(v) is not int or v<0 for v in values):raise ValueError("complete nonnegative integer MC group counts required")
        if self._document["mc_design"]["kind"]=="fixed_n_categories" and sum(values)!=self._document["mc_design"]["total_groups"]:raise ValueError("repeated MC data must retain fixed N")
        return list(values)
    def auxiliary_means(self,latent):
        self.assert_custody()
        return complete_auxiliary_means(self._document,latent)
    def nominal(self,latent):
        self.assert_custody();doc=self._document
        values,raw,denominator=_physical(doc,latent)
        fixed=doc["mc_design"]["kind"]=="fixed_n_categories"
        signal=[(doc["mc_design"]["kappa"]*(x/denominator) if doc["schema_version"] == 2 else doc["mc_design"]["kappa"]*x/denominator) for x in raw] if fixed else raw
        means=[doc["mc_design"]["total_groups"]*v for v in values] if fixed else [c["exposure"]*v for c,v in zip(doc["classes"],values)]
        if any(not math.isfinite(x) for x in signal+means):raise ValueError("derived MC expectation overflow")
        return {"signal_expectation":signal,"raw_mark_expectation":raw,"expected_denominator":denominator,"mc_means":means}
    def auxiliary_logpdf(self,latent,observations=None):
        evaluated=self.nominal(latent);counts=self.counts(observations);fixed=self._document["mc_design"]["kind"]=="fixed_n_categories"
        terms=[math.lgamma(self._document["mc_design"]["total_groups"]+1)] if fixed else []
        for name,n,mean in zip(self._classes,counts,evaluated["mc_means"]):
            value=latent[name] if fixed else mean
            if value==0 and n:return None
            terms.append((n*math.log(value) if n else 0)-math.lgamma(n+1)-(0 if fixed else value))
        result=math.fsum(terms)
        if not math.isfinite(result):raise ValueError("MC auxiliary density overflow")
        return result
    def draw_auxiliary(self,latent,rng):
        evaluated=self.nominal(latent)
        return rng.multinomial(self._document["mc_design"]["total_groups"],[latent[name] for name in self._classes]).tolist() if self._document["mc_design"]["kind"]=="fixed_n_categories" else rng.poisson(evaluated["mc_means"]).tolist()
