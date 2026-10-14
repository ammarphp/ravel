"""Source-bound joined density/sampling API; no scientific execution adapter.

The original published background/auxiliary block is evaluated once. The
separate declared finite-MC law adds one auxiliary experiment. Complete source
response data/code are still supplied and independently reviewed obligations.
"""
from copy import deepcopy
import hashlib
import inspect
import json
import math
import marshal
from pathlib import Path
import sys

from ravel.physics import finite_mc_model as fm
from ravel.physics.mc_auxiliary import _read,MAX_BYTES,MAX_TOTAL_BYTES,MAX_SOURCES


def compact(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()


def response_identity(response):
    """Identity of the admitted module function, excluding dynamic callables.

    This checks direct function state, not purity of transitive globals. Those
    globals/dependencies need a reviewed frozen execution environment.
    """
    if (not inspect.isfunction(response) or response.__closure__ is not None or
            response.__qualname__!=response.__name__ or not response.__name__.isidentifier() or
            response.__defaults__ is not None or response.__kwdefaults__ or response.__dict__):
        raise ValueError("response must be a pure module function with no closure, instance, defaults or mutable function attributes")
    module=sys.modules.get(response.__module__)
    if module is None or response.__globals__ is not vars(module) or getattr(module,response.__name__,None) is not response:
        raise ValueError("response must retain its exact module function binding")
    signature=inspect.signature(response)
    expected=("latent","nominal","source_point","configuration","source_data")
    if tuple(signature.parameters)!=expected or any(p.kind!=inspect.Parameter.POSITIONAL_OR_KEYWORD for p in signature.parameters.values()):
        raise ValueError("response module function needs five explicit state-free input arguments")
    return {"module":response.__module__,"qualname":response.__qualname__,
            "code_sha256":hashlib.sha256(marshal.dumps(response.__code__)).hexdigest()}


class JointPublishedFiniteMC:
    """Executable source-bound joined density and fixed-truth sampling skeleton."""
    def __init__(self,background,mc,*,source_workspace,signal_samples,source_bin_map,
                 response,response_contract,model_id,main_disposition,base="."):
        from ravel.physics.published_background import inspect_workspace
        if main_disposition!="replace_conditional_control_with_bound_published_source":
            raise ValueError("explicit retirement of conditional control main factors required")
        if not isinstance(model_id,str) or not model_id.strip() or not callable(response):
            raise ValueError("distinct joined identity and supplied response implementation required")
        self._background=background;self._mc=mc;self._response=response
        bg=background.contract();self._background_hash=background.contract_sha256
        if hashlib.sha256(compact(bg)).hexdigest()!=self._background_hash:
            raise ValueError("background contract mutated after compilation")
        census=inspect_workspace(source_workspace,signal_samples)
        if census["workspace_sha256"]!=bg["source_workspace_sha256"]:
            raise ValueError("joined source workspace differs from background construction")
        measurement=next(m for m in source_workspace["measurements"] if m["name"]==bg["measurement"])
        poi=measurement["config"]["poi"]
        response_names={name for name,rows in census["occurrences"].items() if name!=poi and
                        any(r["signal"] and r["type"] not in {"staterror","shapesys"} for r in rows)}
        required_coordinates={p for name in response_names for p in bg["active_parameter_names"] if p==name or p.startswith(name+"[")}
        if any(not any(p==name or p.startswith(name+"[") for p in required_coordinates) for name in response_names):
            raise ValueError("source signal response coordinate is missing from retained experiment")
        keys={"background_contract_sha256","source_workspace_sha256","coordinate_dependencies","implementation_pin","callable_identity",
              "configuration","configuration_sha256","source_data_pins","source_workspace_data_id","environment_requirements","independence","provenance"}
        if not isinstance(response_contract,dict) or set(response_contract)!=keys:
            raise ValueError("complete supplied response binding required")
        if response_contract["background_contract_sha256"]!=self._background_hash or response_contract["source_workspace_sha256"]!=census["workspace_sha256"]:
            raise ValueError("response must bind exact joined source/background construction")
        dependencies=response_contract["coordinate_dependencies"]
        fm._ids(dependencies,"response coordinate dependencies",empty=True)
        if set(dependencies)!=required_coordinates:
            raise ValueError("response must cover every retained source signal nuisance and exclude replaced MC coordinates")
        if response_contract["independence"]!="supplied_source_and_new_MC_auxiliaries_independent":
            raise ValueError("source/MC measurement independence requires an explicit supplied design")
        if not isinstance(response_contract["provenance"],str) or not response_contract["provenance"].strip():
            raise ValueError("source response provenance required")
        self._response_identity=response_identity(response)
        if response_contract["callable_identity"]!=self._response_identity:
            raise ValueError("response module/qualified name/code identity differs from its contract")
        if response_contract["environment_requirements"]!="reviewed_frozen_transitive_globals_and_dependencies":
            raise ValueError("transitive response globals/dependencies require a reviewed frozen environment")
        try:
            if not isinstance(response_contract["configuration"],dict):
                raise ValueError("explicit response configuration object required")
            self._configuration_json=compact(response_contract["configuration"])
            fm._load_bytes(self._configuration_json)
        except (TypeError,ValueError) as error:
            raise ValueError("response configuration must be fully serialized finite JSON") from error
        if hashlib.sha256(self._configuration_json).hexdigest()!=response_contract["configuration_sha256"]:
            raise ValueError("response configuration hash differs")
        pins=response_contract["source_data_pins"]
        if not isinstance(pins,list) or not 1<=len(pins)<=MAX_SOURCES:
            raise ValueError("explicit byte-bound response source data required")
        self._response_data={};source_ids=[]
        for data_pin in pins:
            if not isinstance(data_pin,dict) or set(data_pin)!={"id","path","sha256","encoding"} or data_pin["encoding"]!="json":
                raise ValueError("first response skeleton requires named JSON source-data pins")
            source_ids.append(data_pin["id"])
            fm._ids(source_ids,"response source ids")
            path=fm._regular(data_pin["path"],base);raw=_read(path)
            if hashlib.sha256(raw).hexdigest()!=data_pin["sha256"]:
                raise ValueError("response source-data hash differs")
            fm._load_bytes(raw)
            self._response_data[data_pin["id"]]=(path,raw)
            if sum(len(data) for _,data in self._response_data.values())>MAX_TOTAL_BYTES:raise ValueError("response source data exceeds aggregate byte ceiling")
        workspace_data_id=response_contract["source_workspace_data_id"]
        if not isinstance(workspace_data_id,str) or workspace_data_id not in self._response_data:
            raise ValueError("response must identify its pinned source workspace data")
        response_workspace=fm._load_bytes(self._response_data[workspace_data_id][1])
        if hashlib.sha256(compact(response_workspace)).hexdigest()!=bg["source_workspace_sha256"]:
            raise ValueError("response source-data workspace differs from the joined source point")
        pin=response_contract["implementation_pin"]
        if not isinstance(pin,dict) or set(pin)!={"path","sha256"}:
            raise ValueError("response implementation byte pin required")
        implementation=fm._regular(pin["path"],base)
        callable_source=inspect.getsourcefile(response);raw=_read(implementation)
        if callable_source is None or Path(callable_source).resolve()!=implementation or hashlib.sha256(raw).hexdigest()!=pin["sha256"]:
            raise ValueError("supplied response callable differs from its byte-bound implementation")
        self._response_source=implementation;self._response_raw=raw
        if len(raw)+len(self._configuration_json)+sum(len(data) for _,data in self._response_data.values())>MAX_TOTAL_BYTES:raise ValueError("response implementation/configuration/data exceed aggregate byte ceiling")
        expected=[]
        for channel in bg["channel_order"]:
            start,stop=bg["channel_slices"][channel]
            expected.extend((channel,index-start) for index in range(start,stop))
        if not isinstance(source_bin_map,list) or len(source_bin_map)!=len(expected):
            raise ValueError("complete explicit published-to-MC bin permutation required")
        for row,pair in zip(source_bin_map,expected):
            if not isinstance(row,dict) or set(row)!={"channel","bin","mc_bin_id"} or (row["channel"],row["bin"])!=pair or type(row["bin"]) is not int:
                raise ValueError("source bin permutation must follow exact published channel/bin order")
        ids=[r["mc_bin_id"] for r in source_bin_map]
        if len(ids)!=len(set(ids)) or set(ids)!=set(mc.bin_ids):
            raise ValueError("source bin permutation must use every MC bin exactly once")
        self._permutation=tuple(mc.bin_index(name) for name in ids)
        self._contract={"model_id":model_id,"background":bg,"background_contract_sha256":self._background_hash,
                        "MC":mc.contract(),"response":deepcopy(response_contract),"source_bin_map":deepcopy(source_bin_map),
                        "main_disposition":main_disposition,"physics_validated":False,"numerical_inference":False,
                        "scope":"Joined source main/auxiliary plus separate fixed-mark MC density/sampler; no fit, calibration or exclusion"}
        self._contract_sha256=hashlib.sha256(compact(self._contract)).hexdigest()

    @property
    def contract_sha256(self):
        return self._contract_sha256

    def contract(self):
        return deepcopy(self._contract)

    def _assert_response_custody(self):
        if response_identity(self._response)!=self._response_identity:
            raise ValueError("response function identity or executable code changed")
        if _read(fm._regular(str(self._response_source),Path.cwd()))!=self._response_raw:
            raise ValueError("response implementation changed")
        for path,raw in self._response_data.values():
            if _read(fm._regular(str(path),Path.cwd()))!=raw:
                raise ValueError("response source data changed")

    def _signal(self,source_point,latent):
        if hashlib.sha256(compact(self._background.contract())).hexdigest()!=self._background_hash:
            raise ValueError("joined background contract changed")
        self._assert_response_custody()
        # Validate complete source domains/fixed flags before supplied response
        # code runs. This evaluates means, without adding an auxiliary factor.
        self._background.background_means(source_point)
        nominal=self._mc.nominal(latent)["signal_expectation"]
        values=self._response(deepcopy(latent),deepcopy(nominal),deepcopy(source_point),
                              fm._load_bytes(self._configuration_json),{name:fm._load_bytes(raw) for name,(_,raw) in self._response_data.items()})
        self._assert_response_custody()
        values=fm._numbers(values,len(nominal),"complete transported signal expectation")
        if any(v<0 for v in values):
            raise ValueError("transported signal has negative physical NET expectation")
        return {"background_contract_sha256":self._background_hash,"source_point":deepcopy(source_point),
                "means":[values[i] for i in self._permutation],"provenance":self._contract["response"]["provenance"]}

    def evaluate(self,source_point,latent,*,mu,main_observations=None,source_auxiliary_observations=None,mc_observations=None):
        signal=self._signal(source_point,latent)
        source=self._background.join(source_point,signal,mu=mu,observations=main_observations,auxiliary_observations=source_auxiliary_observations)
        mc=self._mc.auxiliary_logpdf(latent,mc_observations)
        finite=source["finite"] and mc is not None
        value=source["logpdf_before_new_mc_auxiliary"]+mc if finite else None
        if value is not None and not math.isfinite(value):
            raise ValueError("joined full density overflows finite arithmetic")
        return {"source":source,"MC_auxiliary_logpdf":mc,"joint_logpdf":value,"finite":bool(finite),
                "zero_probability":not finite,"contract_sha256":self.contract_sha256,"physics_validated":False,"numerical_inference":False}

    def draw_joint_data(self,source_point,latent,*,mu,rng):
        signal=self._signal(source_point,latent)
        source=self._background.join(source_point,signal,mu=mu)
        return {"main":rng.poisson(source["main_means"]).tolist(),
                "source_auxiliary":self._background.draw_auxiliary(source_point,rng),
                "MC_auxiliary":self._mc.draw_auxiliary(latent,rng),
                "sampling":"Repeat all main and both auxiliary experiments at fixed supplied source/MC truth"}
