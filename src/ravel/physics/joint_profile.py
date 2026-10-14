"""Bounded local joint profiling candidate; no official fit or CLs adapter.

General transported responses use explicitly charged finite differences in a
small admitted dimension. Distinct feasible starts and tangent-cone checks are
numerical evidence, not a theorem of global optimality or interval coverage.
"""
from copy import deepcopy
import math
import time
import warnings

import numpy as np
from scipy.optimize import linprog,minimize

from ravel.physics.quantities import _keys,_number


class BudgetExhausted(RuntimeError):pass

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



class WorkBudget:
    def __init__(self,contract,wall_hook=None,*,maximum_wall_seconds=30):
        _keys(contract,("objective_calls","gradient_calls","feasibility_lp_calls","stationarity_lp_calls","maxiter","lp_maxiter","wall_seconds"),label="joint fit budget")
        for key in ("objective_calls","gradient_calls","feasibility_lp_calls","stationarity_lp_calls","maxiter","lp_maxiter"):
            if type(contract[key]) is not int or not 1<=contract[key]<=50000:raise ValueError("explicit positive bounded work counts required")
        if not 0<_number(maximum_wall_seconds,"wall ceiling")<=300:raise ValueError("fit wall ceiling must be at most 300 seconds")
        if not 0<_number(contract["wall_seconds"],"wall seconds")<=maximum_wall_seconds:raise ValueError("local fit wall hook exceeds the declared ceiling")
        self.contract=deepcopy(contract);self.counts={key:0 for key in ("objective_calls","gradient_calls","feasibility_lp_calls","stationarity_lp_calls")}
        self.started=time.monotonic();self.wall_hook=wall_hook;self.exhaustion=None
    def check(self):
        elapsed=time.monotonic()-self.started
        if elapsed>=self.contract["wall_seconds"] or self.wall_hook is not None and self.wall_hook():
            self.exhaustion="wall_hook";raise BudgetExhausted("joint fit wall hook exhausted")
    def charge(self,key):
        self.check()
        if self.counts[key]>=self.contract[key]:
            self.exhaustion=key;raise BudgetExhausted("joint fit "+key+" budget exhausted")
        self.counts[key]+=1
    def lp_options(self):
        self.check()
        return {"maxiter":self.contract["lp_maxiter"],"time_limit":max(.001,self.contract["wall_seconds"]-(time.monotonic()-self.started))}
    def snapshot(self):
        return {"declared":deepcopy(self.contract),"used":dict(self.counts),"elapsed_seconds":time.monotonic()-self.started,"exhaustion":self.exhaustion,
                "enforcement":"Every density probe/gradient/LP is charged, including failed finite-difference probes; wall checked between calls and forwarded to HiGHS. External supervisor required to interrupt a blocking callback/SLSQP call."}


class JointProfiler:
    def __init__(self,joint,background,mc,*,mu_domain,source_bound_semantics,rate_caps,max_free_dimension=8):
        _keys(mu_domain,("initial","upper"),label="numerical mu search")
        if not 0<_number(mu_domain["initial"],"mu initial")<_number(mu_domain["upper"],"mu numerical upper")<=1000:raise ValueError("physical mu lower zero and explicit numerical upper required")
        if type(max_free_dimension) is not int or not 1<=max_free_dimension<=8:raise ValueError("generic finite-difference branch is restricted to at most eight free coordinates")
        self._joint=joint;self._background=background;self._mc=mc;self._mc_document=mc.document();self._source=background.contract();contract=joint.contract()
        if contract["background"]!=self._source or contract["MC"]!=mc.contract():raise ValueError("profiler blocks differ from the bound joined construction")
        names=self._source["active_parameter_names"]
        _keys(source_bound_semantics,names,label="source bound semantics")
        for name,row in source_bound_semantics.items():
            _keys(row,("lower","upper"),label="source bound semantics")
            if any(v not in {"physical","numerical"} for v in row.values()):raise ValueError("source bound physical/numerical meaning must be supplied explicitly")
        domains=self._source["active_parameter_domains"]
        for name in names:
            lo,hi=domains[name]["bounds"]
            if not math.isfinite(lo) or not math.isfinite(hi) or lo>=hi:raise ValueError("finite ordered source search bounds required")
        fixed=self._mc_document["mc_design"]["kind"]=="fixed_n_categories"
        _keys(rate_caps,[] if fixed else mc.class_ids,label="numerical Poisson rate caps")
        if not fixed and any(not c["initial"]<_number(rate_caps[c["id"]],"rate cap")<=1e5 for c in self._mc_document["classes"]):raise ValueError("numerical rate caps must exceed starts; they never limit MC density support")
        self._mu=deepcopy(mu_domain);self._semantics=deepcopy(source_bound_semantics);self._caps=deepcopy(rate_caps);self._dimension=max_free_dimension

    def fit(self,*,fixed_mu=None,data=None,budget,fixed_source=None,fixed_latent=None,wall_hook=None):
        """Complete joint fit, or an explicitly labeled conditional subproblem.

        Only original source `fixed` flags are treated as genuine fixed model
        coordinates. Caller masks are retained separately and never relabeled
        as a full nuisance profile. Fixed-N optimization eliminates the last
        probability algebraically while preserving every category in density.
        """
        work=WorkBudget(budget,wall_hook);attempts=[];seed_records=[];starts=[];probe_refusals=[]
        if data is not None:
            _keys(data,("main","source_auxiliary","MC_auxiliary"),label="complete repeated joint data")
        supplied={} if data is None else {"main_observations":data["main"],"source_auxiliary_observations":data["source_auxiliary"],"mc_observations":data["MC_auxiliary"]}
        counts=self._mc.counts(None if data is None else data["MC_auxiliary"])
        if fixed_mu is not None and not 0<=_number(fixed_mu,"fixed mu")<=self._mu["upper"]:raise ValueError("fixed mu outside declared search")
        masks={} if fixed_source is None else deepcopy(fixed_source)
        if not isinstance(masks,dict) or not set(masks)<=set(self._source["active_parameter_names"]):raise ValueError("unknown conditional source mask")
        domains=self._source["active_parameter_domains"];source_initial={name:row["initial"] for name,row in domains.items()}
        for name,value in masks.items():
            value=_number(value,"conditional source value");lo,hi=domains[name]["bounds"]
            if not lo<=value<=hi or domains[name]["fixed"] and value!=domains[name]["initial"]:raise ValueError("conditional mask violates genuine source fixed/domain semantics")
            source_initial[name]=value
        if fixed_latent is not None:self._mc.nominal(fixed_latent)
        classes=self._mc_document["classes"];fixed_n=self._mc_document["mc_design"]["kind"]=="fixed_n_categories"
        axes=[];bounds=[];initial=[];bound_kinds=[]
        if fixed_mu is None:
            axes.append("mu");initial.append(self._mu["initial"]);bounds.append((0.,self._mu["upper"]));bound_kinds.append(("physical","numerical"))
        source_axes=[name for name in self._source["active_parameter_names"] if not domains[name]["fixed"] and name not in masks]
        for name in source_axes:
            axes.append("source:"+name);initial.append(domains[name]["initial"]);bounds.append(tuple(domains[name]["bounds"]));bound_kinds.append((self._semantics[name]["lower"],self._semantics[name]["upper"]))
        latent_offset=len(axes);floor=1e-10
        if fixed_latent is None:
            for c,n in zip(classes[:-1] if fixed_n else classes,counts):
                axes.append("MC:"+c["id"]);initial.append(c["initial"]);bounds.append((floor if n else 0.,1. if fixed_n else self._caps[c["id"]]));bound_kinds.append(("numerical" if n else "physical","physical" if fixed_n else "numerical"))
        dimension=len(axes)
        if dimension>self._dimension:raise ValueError("admitted finite-difference dimension exceeded; an analytic derivative branch is required")
        T=np.zeros((len(classes),dimension));constant=np.zeros(len(classes))
        if fixed_latent is not None:constant=np.array([fixed_latent[c["id"]] for c in classes])
        else:
            for i in range(len(classes)-int(fixed_n)):T[i,latent_offset+i]=1.
            if fixed_n:T[-1,latent_offset:]=-1.;constant[-1]=1.
        W=np.array([c["contribution"] for c in classes]).T
        rows=list(W@T);intercepts=list(W@constant);labels=[{"kind":"net","bin":b["id"],"physical":True} for b in self._mc_document["bins"]]
        if fixed_n:
            d=np.array([c["denominator_mark"] for c in classes]);rows.append(d@T);intercepts.append(float(d@constant)-floor);labels.append({"kind":"denominator_floor","physical":False})
            if fixed_latent is None:
                rows.extend([T[-1],-T[-1]]);intercepts.extend([constant[-1]-(floor if counts[-1] else 0.),1.-constant[-1]])
                labels.extend([{"kind":"last_probability_lower","physical":not bool(counts[-1])},{"kind":"last_probability_upper","physical":True}])
        G=np.array(rows).reshape((-1,dimension)) if dimension else np.zeros((len(rows),0));h=np.array(intercepts)
        def parameters(x):
            source=dict(source_initial);offset=int(fixed_mu is None)
            for i,name in enumerate(source_axes):source[name]=float(x[offset+i])
            probabilities=T@x+constant
            return {"mu":float(x[0]) if fixed_mu is None else fixed_mu,"source":source,"latent":{c["id"]:float(v) for c,v in zip(classes,probabilities)}}
        recipe={"coordinate_order":axes,"source_domains":deepcopy(domains),"source_bound_semantics":deepcopy(self._semantics),"true_fixed_source_coordinates":[name for name,row in domains.items() if row["fixed"]],
                "conditional_masks":{"source":masks,"latent":deepcopy(fixed_latent),"mu":fixed_mu},"MC_parameterization":"last category eliminated algebraically; all classes retained in density" if fixed_n else "complete nonnegative Poisson rates",
                "numerical_floors":{"positive_observation_rate_or_probability":floor,"expected_denominator":floor},"numerical_rate_caps":deepcopy(self._caps),"numerical_mu_cap":self._mu["upper"],"joint_contract_sha256":self._joint.contract_sha256}
        def finish(**fields):
            return {"verified":False,"attempts":attempts,"planned_start_count":len(starts),"unlaunched_start_count":max(0,len(starts)-len(attempts)),"start_generation":seed_records,"density_probe_refusals":probe_refusals,"recipe":recipe,"work":work.snapshot(),"physics_validated":False,"global_optimum_certified":False,
                    "scope":"Bounded numerical joint profiling evidence; no coverage, CLs or exclusion claim",**fields}
        selected=[i for i,c in enumerate(classes) if any(c["contribution"])]
        if fixed_mu is None and fixed_latent is None and all(counts[i]==0 for i in selected):
            return finish(status="unresolved_strength_recession",failure="all nominal selected MC categories observed zero: finite strength endpoint not established; source-dependent marked response can require additional recession analysis")
        def evaluation(x):
            work.charge("objective_calls");p=parameters(np.asarray(x))
            if any(not lo-1e-14<=v<=hi+1e-14 for v,(lo,hi) in zip(x,bounds)) or np.any(G@x+h<-1e-12):return None
            try:
                result=self._joint.evaluate(p["source"],p["latent"],mu=p["mu"],**supplied)
            except (ValueError,OverflowError,FloatingPointError) as error:
                if len(probe_refusals)<16:probe_refusals.append({"coordinates":list(map(float,x)),"kind":type(error).__name__,"error":str(error)})
                return None
            work.check()
            if not result["finite"]:
                if len(probe_refusals)<16:probe_refusals.append({"coordinates":list(map(float,x)),"kind":"zero_probability"})
                return None
            aux=[p["source"][r["coordinate"]]*(1. if r["pdf"]=="normal" else r["factor"]) for r in self._source["retained_auxiliaries"]]
            means=result["source"]["main_means"]+aux+self._mc.nominal(p["latent"])["mc_means"]
            work.check()
            return -result["joint_logpdf"],np.array(means)
        def objective(x):
            result=evaluation(x);return math.inf if result is None else result[0]
        def derivatives(x):
            work.charge("gradient_calls");base=evaluation(x)
            if base is None:raise ValueError("derivative requested at nonfinite/infeasible point")
            grad=[];columns=[]
            for i in range(dimension):
                step=2e-5*max(1.,abs(float(x[i])));samples=[]
                for sign in (-1.,1.):
                    probe=np.array(x,copy=True);probe[i]+=sign*step
                    if not bounds[i][0]<=probe[i]<=bounds[i][1]:samples.append(None)
                    else:samples.append(evaluation(probe))
                lo,hi=samples
                if lo is not None and hi is not None:
                    grad.append((hi[0]-lo[0])/(2*step));columns.append((hi[1]-lo[1])/(2*step))
                elif lo is not None:
                    grad.append((base[0]-lo[0])/step);columns.append((base[1]-lo[1])/step)
                elif hi is not None:
                    grad.append((hi[0]-base[0])/step);columns.append((hi[1]-base[1])/step)
                else:raise ValueError("no feasible coordinate probe for bounded derivative; coupled boundary unresolved")
            gradient=np.array(grad);jacobian=np.array(columns).T
            if not np.all(np.isfinite(gradient)) or not np.all(np.isfinite(jacobian)):raise ValueError("finite-difference derivative overflows")
            return gradient,jacobian
        def append_start(x,origin):
            if any(not lo<=v<=hi for v,(lo,hi) in zip(x,bounds)) or np.any(G@x+h<-1e-12):return
            if any(np.max(np.abs(x-y)/np.maximum(1.,np.maximum(np.abs(x),np.abs(y))))<1e-6 for y in starts):return
            if evaluation(x) is not None:starts.append(np.array(x));seed_records.append({"kind":"admitted_seed","origin":origin,"coordinates":list(map(float,x))})
        try:
            work.check()
            if dimension==0:
                result=evaluation(np.array([]))
                return finish(verified=result is not None,status="fully_conditioned_density",parameters=parameters(np.array([])),nll=None if result is None else result[0],global_optimum_certified=result is not None)
            init=np.array(initial);append_start(init,"source_initial")
            # Same feasible-target/convex-mixing construction as production
            # cd10570 fixed-N repair, extended to full source coordinates. LPs
            # find seed targets only; they do not solve the joint likelihood.
            for i in range(dimension):
                for sign in (1.,-1.):
                    work.charge("feasibility_lp_calls");direction=np.zeros(dimension);direction[i]=sign
                    target=linprog(direction,A_ub=-G,b_ub=h,bounds=bounds,method="highs",options=work.lp_options())
                    success=bool(target.success and target.x is not None and np.all(np.isfinite(target.x)))
                    seed_records.append({"kind":"feasibility_LP","coordinate":axes[i],"sign":sign,"success":success,"message":str(target.message),"target":target.x.tolist() if success else None})
                    if success:
                        for fraction in (.15,.3):append_start((1-fraction)*init+fraction*target.x,"feasible_convex_mixture")
                    if len(starts)>=3:break
                if len(starts)>=3:break
            if len(starts)<2:return finish(status="unresolved_seeds",failure="fewer than two distinct feasible starting points")
        except BudgetExhausted as error:return finish(status="budget_exhausted",failure=str(error))
        except Exception as error:
            seed_records.append({"kind":"seed_generation_exception","exception_type":type(error).__name__,"error":str(error)})
            return finish(status="unresolved_seeds",failure="seed generation failed; record retained")
        for index,start in enumerate(starts[:3]):
            attempt={"index":index,"start_coordinates":start.tolist(),"start_parameters":parameters(start),"verified":False};attempts.append(attempt)
            caught=[]
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    result=minimize(objective,start.copy(),jac=lambda x:derivatives(x)[0],bounds=bounds,
                                    constraints=[{"type":"ineq","fun":lambda x:G@x+h,"jac":lambda x:G}],method="SLSQP",options={"maxiter":budget["maxiter"],"ftol":1e-10})
                x=np.asarray(result.x)
                witness={"coordinate_order":list(axes),"coordinates":_diagnostic_values(x),
                         "activity_rule":"literal_zero_physical_slack; negative_physical_slack_refuses; numerical_proximity_conservative_refusal",
                         "gradient_tolerance":2e-4,"nonfinite_diagnostic_values":"represented_by_null; never_admitted_as_finite"}
                attempt["stationarity_witness"]=witness
                work.check()
                if np.shape(x)!=(dimension,):
                    raise ValueError("optimizer returned coordinate population differs from declared fit")
                witness.update({"coordinate_bounds":_diagnostic_values(bounds),"bound_semantics":_diagnostic_values(bound_kinds),
                         "coordinate_slacks":_diagnostic_values([[v-lo,hi-v] for v,(lo,hi) in zip(x,bounds)]),
                         "linear_constraints":{"matrix":_diagnostic_values(G),"offset":_diagnostic_values(h),
                             "residuals":_diagnostic_values(G@x+h),"labels":deepcopy(labels)}})
                value=evaluation(x)
                if value is None:raise ValueError("optimizer returned nonfinite/infeasible point")
                gradient,J=derivatives(x);active=[];directions=[]
                witness["raw_coordinate_gradient"]=_diagnostic_values(gradient)
                for i,(lo,hi) in enumerate(bounds):
                    scale=max(1.,abs(float(x[i])))
                    at_lo=_tangent_active(float(x[i])-lo,1e-7*scale,physical=bound_kinds[i][0]=="physical")
                    at_hi=_tangent_active(hi-float(x[i]),1e-7*scale,physical=bound_kinds[i][1]=="physical")
                    directions.append((0. if at_lo else -scale,0. if at_hi else scale))
                    if at_lo:active.append({"coordinate":axes[i],"side":"lower","physical":bound_kinds[i][0]=="physical"})
                    if at_hi:active.append({"coordinate":axes[i],"side":"upper","physical":bound_kinds[i][1]=="physical"})
                linear=[]
                for row,residual,label in zip(G,G@x+h,labels):
                    if _tangent_active(float(residual),1e-7*max(1.,float(np.linalg.norm(row))),physical=label["physical"]):linear.append(-row);active.append(deepcopy(label))
                witness["lp"]={"objective":_diagnostic_values(gradient),"direction_bounds":_diagnostic_values(directions),
                    "A_ub":_diagnostic_values(linear) if linear else None,"b_ub":[0.]*len(linear) if linear else None,
                    "A_eq":None,"b_eq":None,"active_constraints":deepcopy(active)}
                work.charge("stationarity_lp_calls")
                stationary=linprog(gradient,A_ub=np.array(linear) if linear else None,b_ub=np.zeros(len(linear)) if linear else None,bounds=directions,method="highs",options=work.lp_options())
                witness["lp"]["result"]={"success":bool(stationary.success),"message":str(stationary.message),
                    "direction":_diagnostic_values(getattr(stationary,"x",None)),"objective":_diagnostic_values(getattr(stationary,"fun",None))}
                violation=max(0.,-float(stationary.fun)) if stationary.success and math.isfinite(float(stationary.fun)) else None
                norms=np.linalg.norm(J,axis=0);singular=np.linalg.svd(J/np.where(norms>0,norms,1),compute_uv=False)
                rank=int(np.sum(singular>max(1e-9*float(singular[0]),1e-12)))
                valid=bool(result.success and violation is not None and violation<=2e-4 and rank==dimension and all(row["physical"] for row in active))
                attempt.update(success=bool(result.success),message=str(result.message),iterations=int(result.nit),parameters=parameters(x),nll=float(value[0]),verified=valid,
                               distribution_mean_vector=value[1].tolist(),main_means=value[1][:sum(stop-start for start,stop in self._source["channel_slices"].values())].tolist(),
                               active_bounds=active,tangent_descent_violation=violation,stationarity_lp={"success":bool(stationary.success),"message":str(stationary.message)},
                               local_identifiability={"rank":rank,"free_dimension":dimension,"singular_values":singular.tolist(),"scope":"Mean-Jacobian rank only; does not exclude global recession or nonregular boundary laws"})
            except BudgetExhausted as error:
                attempt.update(failure_kind="budget_exhausted",error=str(error));break
            except Exception as error:
                attempt.update(failure_kind="numerical_or_verification_exception",error=str(error),exception_type=type(error).__name__)
            finally:attempt["optimizer_warnings"]=[{"category":w.category.__name__,"message":str(w.message)} for w in caught]
        if work.exhaustion:return finish(status="budget_exhausted",failure="fit work budget exhausted; partial attempts retained")
        candidates=[a for a in attempts if a["verified"]]
        if len(candidates)<2:return finish(status="unresolved_numerical_profile",failure="fewer than two distinct feasible stationary identified attempts; artificial bounds are not physical information")
        best=min(candidates,key=lambda a:a["nll"]);spread=max(a["nll"] for a in candidates)-best["nll"]
        return finish(verified=spread<=1e-5,status="bounded_multistart_agreement" if spread<=1e-5 else "unresolved_multistart_disagreement",parameters=best["parameters"],nll=best["nll"],multi_start_nll_spread=spread)

    def profile(self,strengths,*,budget_per_fit,data=None,wall_hook=None):
        if not isinstance(strengths,list) or not 1<=len(strengths)<=8:raise ValueError("bounded explicit profile grid required")
        # Validate the entire grid before paying for a global fit. Duplicate
        # strengths are refused, rather than spending another fit budget on an
        # identical hypothesis without an explicit repeated-fit protocol.
        values=[_number(mu,"profile strength") for mu in strengths]
        if any(not 0<=mu<=self._mu["upper"] for mu in values) or len(set(values))!=len(values):raise ValueError("profile strengths must be unique and within the declared search")
        WorkBudget(budget_per_fit) # validate the complete per-fit budget early
        best=self.fit(data=data,budget=budget_per_fit,wall_hook=wall_hook);rows=[]
        for mu in values:
            conditional=self.fit(fixed_mu=mu,data=data,budget=budget_per_fit,wall_hook=wall_hook);statistic=None
            if best["verified"] and conditional["verified"]:
                delta=2*(conditional["nll"]-best["nll"])
                if delta>=-1e-5:statistic=max(0.,delta)
                else:conditional["verified"]=False;conditional["failure"]="conditional fit improves claimed free minimum"
            rows.append({"mu":mu,"fit":conditional,"twice_delta_nll":statistic})
        return {"verified":bool(best["verified"] and all(row["fit"]["verified"] and row["twice_delta_nll"] is not None for row in rows)),"global_fit":best,"profiles":rows,
                "declared_maximum_fit_calls":1+len(strengths),"global_optimum_certified":False,"scope":"Two-sided likelihood-ratio diagnostic only; no calibrated confidence, CLs or exclusion"}
