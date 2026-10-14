"""Qualified analytic NumPy graph for a published-source/finite-MC join.

The signal extension rescales the published non-MC response per target bin by
the latent fixed-mark signal expectation. It is a new statistical construction,
not evidence about native detector variations or a generator sampling law.
Only pyhf 0.7.6 code4/code4p without clipping is admitted. Numerical profiling
is bounded, retains failed attempts, and makes no global or coverage claim.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import warnings

import numpy as np
from scipy.optimize import linprog, minimize

from ravel.physics.joint_profile import WorkBudget, BudgetExhausted
from ravel.physics.mc_auxiliary import compact, _read
from ravel.physics.published_background import inspect_workspace, MC_TYPES
from ravel.physics.quantities import _keys, _number
from ravel.physics.marked_response_provider import MarkedResponseProvider, assemble_main_jet
from ravel.physics.normalized_profile_domain import relative_denominator_domain


MAX_PARAMETERS = 256
MAX_MODIFIER_OCCURRENCES = 10000


def _code4_coefficients(hi, lo):
    """Six Hermite conditions: endpoint value, first and second derivative."""
    if hi <= 0 or lo <= 0:
        raise ValueError("analytic code4 requires strictly positive source factors")
    j = np.arange(1, 7, dtype=float)
    matrix = np.array([np.ones(6), (-1.)**j, j, j*(-1.)**(j-1),
                       j*(j-1), j*(j-1)*(-1.)**(j-2)])
    target = np.array([hi-1, lo-1, hi*math.log(hi), -lo*math.log(lo),
                       hi*math.log(hi)**2, lo*math.log(lo)**2])
    return np.linalg.solve(matrix, target)


def _code4(alpha, hi, lo, coefficients):
    if alpha >= 1:
        value = hi**alpha
        return value, value*math.log(hi)
    if alpha <= -1:
        value = lo**(-alpha)
        return value, -value*math.log(lo)
    powers = np.arange(1, 7)
    return 1+float(coefficients @ (alpha**powers)), float((powers*coefficients) @ (alpha**(powers-1)))


def _code4p(alpha, nominal, hi, lo):
    up, down = hi-nominal, nominal-lo
    if alpha >= 1:
        return alpha*up, up
    if alpha <= -1:
        return alpha*down, down
    symmetric, asymmetric = .5*(up+down), (up-down)/16.
    return (alpha*symmetric+(15*alpha**2-10*alpha**4+3*alpha**6)*asymmetric,
            symmetric+(30*alpha-40*alpha**3+18*alpha**5)*asymmetric)


class _SourceGraph:
    """Source samples retain additive-before-multiplicative pyhf ordering.

    Vector modifier coordinates use the pinned compiler's exact access field;
    channel-local or pooled gamma indices are never inferred from text names.
    No finite differences, callback dispatch or backend mutation occur here.
    """
    def __init__(self, workspace, background, signal_samples, *, absolute_response=False):
        import pyhf
        model = background._model
        admitted = {"histosys":{"interpcode":"code4p"},"normsys":{"interpcode":"code4"}}
        if background.contract()["modifier_settings"] != admitted or model.config.modifier_settings != admitted:
            raise ValueError("analytic source graph requires exact code4p/code4 modifier settings")
        for kind, code in (("histosys","code4p"),("normsys","code4")):
            applier = model.main_model.modifiers_appliers[kind]
            interpolator = getattr(applier,"interpolator",None)
            if applier.interpcode != code or interpolator is not None and type(interpolator) is not getattr(pyhf.interpolators,code):
                raise ValueError("compiled source interpolation differs from qualified analytic graph")
        if model.main_model.clip_sample_data is not None or model.main_model.clip_bin_data is not None:
            raise ValueError("clipped source graphs require a separately qualified nonsmooth derivative branch")
        self.names = tuple(background.contract()["active_parameter_names"])
        self.indices = {name: i for i, name in enumerate(self.names)}
        self.nbins = model.config.nmaindata
        self.samples = []
        noccurrences = sum(len(s["modifiers"]) for c in workspace["channels"] for s in c["samples"])
        if len(self.names) > MAX_PARAMETERS or self.nbins > (64 if absolute_response else 8) or noccurrences > MAX_MODIFIER_OCCURRENCES:
            raise ValueError("analytic source graph exceeds explicit size admission")
        self.occurrences = noccurrences
        by_channel = {c["name"]: c for c in workspace["channels"]}
        for channel in model.config.channels:
            part = model.config.channel_slices[channel]
            for sample in by_channel[channel]["samples"]:
                signal = sample["name"] in signal_samples[channel]
                if absolute_response and signal:
                    continue  # complete absolute provider replaces this signal response once
                nominal = np.array(sample["data"], dtype=float)
                additions, factors = [], []
                for modifier in sample["modifiers"]:
                    kind, name, data = modifier["type"], modifier["name"], modifier["data"]
                    if signal and (kind in MC_TYPES or name == model.config.poi_name):
                        continue
                    if name == model.config.poi_name:
                        raise ValueError("unremoved background source POI")
                    if kind in {"histosys", "normsys", "normfactor", "lumi"}:
                        pset = model.config.par_map[name]["slice"]
                        if pset.stop-pset.start != 1:
                            raise ValueError("source scalar modifier has nonscalar parameter set")
                        index = self.indices[model.config.par_names[pset.start]]
                        indices = np.full(len(nominal), index, dtype=int)
                    elif kind in {"staterror", "shapesys", "shapefactor"}:
                        applier = model.main_model.modifiers_appliers[kind]
                        order = [n for n, t in model.config.modifiers if t == kind]
                        full = np.asarray(applier._access_field, dtype=int)[order.index(name), 0, part]
                        indices = np.array([self.indices[model.config.par_names[int(i)]] for i in full], dtype=int)
                    else:
                        raise ValueError("unsupported analytic source modifier family: "+kind)
                    if kind == "histosys":
                        additions.append((index, np.array(data["hi_data"], dtype=float), np.array(data["lo_data"], dtype=float)))
                    elif kind == "normsys":
                        hi, lo = float(data["hi"]), float(data["lo"])
                        factors.append((kind, indices, hi, lo, _code4_coefficients(hi, lo)))
                    else:
                        factors.append((kind, indices, None, None, None))
                self.samples.append((signal, part, nominal, additions, factors))
        # The reference is the source nominal nuisance response, not arbitrary
        # measurement initial values (which may be overridden by the source).
        nominal_point = {}
        for name in self.names:
            original_index = model.config.par_names.index(name)
            pset_name = next(n for n, row in model.config.par_map.items() if row["slice"].start <= original_index < row["slice"].stop)
            kind = next(t for n, t in model.config.modifiers if n == pset_name)
            nominal_point[name] = 0. if kind in {"histosys", "normsys"} else 1.
        self.nominal_signal = self.evaluate(nominal_point)[2]
        if not absolute_response and np.any(self.nominal_signal <= 0):
            raise ValueError("positive source nominal signal in every target bin required; zero-bin migration transport is unsupported")

    def evaluate(self, point):
        vector = np.array([point[name] for name in self.names])
        background, signal = np.zeros(self.nbins), np.zeros(self.nbins)
        jb, js = np.zeros((self.nbins, len(self.names))), np.zeros((self.nbins, len(self.names)))
        with np.errstate(over="raise", invalid="raise", divide="raise"):
            for is_signal, part, nominal, additions, factors in self.samples:
                value, jac = nominal.copy(), np.zeros((len(nominal), len(self.names)))
                for index, hi, lo in additions:
                    delta, derivative = _code4p(vector[index], nominal, hi, lo)
                    value += delta
                    jac[:, index] += derivative
                for kind, indices, hi, lo, coefficients in factors:
                    if kind == "normsys":
                        factor, derivative = _code4(vector[indices[0]], hi, lo, coefficients)
                        factor = np.full(len(nominal), factor)
                        derivative = np.full(len(nominal), derivative)
                    else:
                        factor, derivative = vector[indices], np.ones(len(nominal))
                    old = value.copy()
                    value *= factor
                    jac *= factor[:, None]
                    # No division by a factor: a zero gamma retains its exact
                    # nonzero product derivative, including shared factors.
                    jac[np.arange(len(nominal)), indices] += old*derivative
                if is_signal:
                    signal[part] += value
                    js[part] += jac
                else:
                    background[part] += value
                    jb[part] += jac
        if any(not np.all(np.isfinite(v)) for v in (background, signal, jb, js)):
            raise ValueError("analytic source expectation or Jacobian overflow")
        return background, jb, signal, js


class AnalyticPublishedJoint:
    """Complete density and analytic gradient for one source-bound new model.

    The admitted signal law is explicit: latent MC expectation times the ratio
    of the complete published non-MC signal response to its nominal response.
    Correlations of variation marks with MC/calibration are not established.
    """
    def __init__(self, background, mc, *, source_workspace, signal_samples,
                 source_bin_map, model_id, response_assumptions, response_provider=None):
        import pyhf
        if pyhf.__version__ != "0.7.6" or pyhf.get_backend()[0].name != "numpy":
            raise ValueError("analytic graph requires pinned pyhf 0.7.6 NumPy runtime")
        if not isinstance(model_id, str) or not model_id.strip() or not isinstance(response_assumptions, list) or len(response_assumptions) < 2 or any(not isinstance(s, str) or not s.strip() for s in response_assumptions):
            raise ValueError("distinct model identity and explicit response/independence assumptions required")
        raw = compact(source_workspace)
        if len(raw) > 8*1024**2:
            raise ValueError("source workspace exceeds 8 MiB admission")
        census = inspect_workspace(source_workspace, signal_samples)
        source = background.contract()
        if census["workspace_sha256"] != source["source_workspace_sha256"]:
            raise ValueError("analytic source differs from the exact bound background workspace")
        for row in source["retained_auxiliaries"]:
            if row["pdf"] not in {"normal", "poisson"} or row["sigma"] <= 0 or row["factor"] <= 0:
                raise ValueError("positive widths/factors and normal/Poisson source auxiliaries required")
        expected = [(name, i) for name in source["channel_order"] for i in range(source["channel_slices"][name][1]-source["channel_slices"][name][0])]
        if not isinstance(source_bin_map, list) or len(source_bin_map) != len(expected):
            raise ValueError("complete published-to-MC bin permutation required")
        for row, pair in zip(source_bin_map, expected):
            _keys(row, ("channel", "bin", "mc_bin_id"), label="source bin mapping")
            if type(row["bin"]) is not int or (row["channel"], row["bin"]) != pair:
                raise ValueError("exact source channel/bin order required")
        ids = [r["mc_bin_id"] for r in source_bin_map]
        if set(ids) != set(mc.bin_ids) or len(ids) != len(set(ids)):
            raise ValueError("all MC target bins required exactly once")
        self._permutation = tuple(mc.bin_index(name) for name in ids)
        self._background, self._mc = background, mc
        self._source, self._document = source, mc.document()
        self._provider = response_provider
        if response_provider is not None:
            if type(response_provider) is not MarkedResponseProvider:
                raise ValueError("exact byte-bound marked response provider required")
            poi = background._model.config.poi_name
            response_names = {name for name, rows in census["occurrences"].items() if name != poi and
                              any(row["signal"] and row["type"] not in MC_TYPES for row in rows)}
            dependencies = {n for name in response_names for n in source["active_parameter_names"]
                            if n == name or n.startswith(name+"[")}
            if any(not any(n == name or n.startswith(name+"[") for n in dependencies) for name in response_names):
                raise ValueError("retained source signal dependency absent")
            response_provider.bind(source, mc, dependencies, ids)
        self._graph = _SourceGraph(json.loads(raw), background, deepcopy(signal_samples), absolute_response=response_provider is not None)
        self._names = tuple(source["active_parameter_names"])
        self._class_ids = tuple(mc.class_ids)
        self._W = np.array([c["contribution"] for c in self._document["classes"]], dtype=float).T[self._permutation, :]
        self._d = np.array([c["denominator_mark"] or 0. for c in self._document["classes"]])
        self._observed = list(background._source_data[:self._graph.nbins])
        self._contract = {"schema":"analytic-published-MC-join-v1", "model_id": model_id, "background": source, "MC": mc.contract(),
                          "source_bin_map": deepcopy(source_bin_map), "signal_samples": deepcopy(signal_samples),
                          "response_extension":"latent_per_bin_times_published_non_MC_signal_over_source_nominal", "response_assumptions":deepcopy(response_assumptions),
                          "sampling":{"law":"repeat_all_main_source_auxiliary_and_MC_measurements_at_fixed_supplied_truth","draw_order":["source_ordered_main_Poisson","retained_source_auxiliary_order","complete_MC_class_order"],"nuisance_prior_draws":False},
                          "implementation":{"module":__name__,"qualified_class":"AnalyticPublishedJoint","sha256":hashlib.sha256(_read(Path(__file__))).hexdigest(),"pyhf":"0.7.6","histosys":"code4p","normsys":"code4","clipping":"refused","environment_requirement":"reviewed frozen transitive Python/NumPy/SciPy/pyhf dependency environment; dynamic mutation unsupported"},
                          "resource_admission":{"maximum_source_bytes":8*1024**2,"maximum_source_coordinates":MAX_PARAMETERS,"maximum_modifier_occurrences":MAX_MODIFIER_OCCURRENCES,"maximum_target_bins":8},
                          "scope":"Exact admitted graph/new MC law; no native generator, globality, calibration or physics qualification", "physics_validated":False}
        if self._provider is not None:
            self._contract.update(schema="analytic-published-MC-absolute-response-v2",
                                  response_extension="absolute_complete_marked_response",
                                  response_provider=self._provider.contract())
            self._contract["resource_admission"]["maximum_target_bins"] = 64
        self.contract_sha256 = hashlib.sha256(compact(self._contract)).hexdigest()

    def contract(self):
        return deepcopy(self._contract)

    def physical_constraints(self, source_point):
        """Nonnegative aggregate background and transported signal response.

        Negative individual morphed samples are not clipped: the original
        pyhf sample algebra is preserved. Aggregate negative signal or
        background expectations are outside this joined physical domain.
        """
        if self._provider is not None:
            raise ValueError("absolute response constraints require complete latent coordinates; use physical_constraints_at")
        self._background._point(source_point)
        b, jb, s, js = self._graph.evaluate(source_point)
        return np.concatenate((b, s)), np.vstack((jb, js))

    def physical_constraints_at(self, source_point, latent):
        """Constraints and columns [source, complete MC] for either response law."""
        self._background._point(source_point)
        b, jb, s, js = self._graph.evaluate(source_point)
        if self._provider is None:
            return np.concatenate((b, s)), np.column_stack((np.vstack((jb, js)), np.zeros((2*len(b), len(self._class_ids)))))
        jet = self._provider.jet(source_point, latent)
        return np.concatenate((b, jet["signal"])), np.vstack((
            np.column_stack((jb, np.zeros((len(b), len(self._class_ids))))),
            np.column_stack((jet["source_jacobian"], jet["latent_jacobian"]))))

    def supported_mc_categories(self):
        return self._provider.supported_categories() if self._provider is not None else [
            i for i, c in enumerate(self._document["classes"]) if any(c["contribution"])]

    def validate_data(self, data):
        """Admit complete repeated observations before any numerical work."""
        _keys(data, ("main", "source_auxiliary", "MC_auxiliary"), label="complete repeated joint data")
        main, aux = data["main"], data["source_auxiliary"]
        if not isinstance(main, list) or len(main) != self._graph.nbins:
            raise ValueError("complete source-ordered main observations required")
        if any(_number(v, "main observation") < 0 for v in main):
            raise ValueError("negative main observation")
        rows = self._source["retained_auxiliaries"]
        if not isinstance(aux, list) or len(aux) != len(rows):
            raise ValueError("complete retained source auxiliary observations required")
        for row, value in zip(rows, aux):
            value = _number(value, "source auxiliary observation")
            if row["pdf"] == "poisson" and value < 0:
                raise ValueError("negative Poisson source auxiliary observation")
        self._mc.counts(data["MC_auxiliary"])
        return deepcopy(data)

    def draw_joint_data(self, source_point, latent, *, mu, rng):
        """Return three fit-ready data arrays, repeating every measurement.

        Truth coordinates are fixed; no nuisance-prior randomization occurs.
        Draw order is main, source auxiliaries, complete MC support. Density of
        the *old* observed data is not required: a zero-mean truth may legally
        generate zero counts although it gives old positive counts probability
        zero. An explicit Generator supplies the independently retained seed.
        """
        if self._provider is not None:
            raise ValueError("absolute marked response sampling requires separate complete repeated-experiment qualification")
        if not isinstance(rng, np.random.Generator):
            raise ValueError("explicit NumPy Generator required")
        mu = _number(mu, "mu")
        if mu < 0:
            raise ValueError("physical mu must be nonnegative")
        self._background._point(source_point)
        nominal = self._mc.nominal(latent)
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                b, _, published, _ = self._graph.evaluate(source_point)
                if np.any(b < 0) or np.any(published < 0):
                    raise ValueError("negative aggregate source background or signal expectation")
                signal = np.array(nominal["signal_expectation"])[list(self._permutation)]*published/self._graph.nominal_signal
                means = b+mu*signal
                if not np.all(np.isfinite(means)):
                    raise ValueError("nonfinite sampling expectation")
                data = {"main":rng.poisson(means).tolist(),
                        "source_auxiliary":self._background.draw_auxiliary(source_point,rng),
                        "MC_auxiliary":self._mc.draw_auxiliary(latent,rng)}
        except (OverflowError, FloatingPointError) as error:
            raise ValueError("analytic joined sampling expectation overflow") from error
        self._mc.assert_custody()
        return self.validate_data(data)

    def evaluate_with_gradient(self, source_point, latent, *, mu,
                               main_observations=None, source_auxiliary_observations=None,
                               mc_observations=None):
        """NLL/gradient with columns [mu, retained source, complete MC classes].

        Fixed-N gradients are derivatives of an extension off the simplex;
        the optimizer must apply its simplex tangent map. Zero-mean zero-count
        Poisson factors have the exact one-sided mean derivative one. A
        zero-probability positive observation has no finite gradient.
        """
        try:
            with np.errstate(over="raise", invalid="raise", divide="raise"):
                return self._evaluate_with_gradient(source_point, latent, mu=mu,
                    main_observations=main_observations, source_auxiliary_observations=source_auxiliary_observations,
                    mc_observations=mc_observations)
        except (OverflowError, FloatingPointError) as error:
            raise ValueError("analytic joined density/gradient overflow") from error

    def _evaluate_with_gradient(self, source_point, latent, *, mu,
                                main_observations=None, source_auxiliary_observations=None,
                                mc_observations=None):
        mu = _number(mu, "mu")
        if mu < 0:
            raise ValueError("physical mu must be nonnegative")
        self._background._point(source_point)
        nominal = self._mc.nominal(latent) if self._provider is None else self._mc.auxiliary_means(latent)
        counts = self._mc.counts(mc_observations)
        rates = np.array([latent[name] for name in self._class_ids], dtype=float)
        b, jb, published, jp = self._graph.evaluate(source_point)
        if self._provider is None:
            if np.any(b < 0) or np.any(published < 0):
                raise ValueError("negative aggregate source background or signal expectation")
            reference = self._graph.nominal_signal
            factor, jfactor = published/reference, jp/reference[:, None]
            snom = np.array(nominal["signal_expectation"])[list(self._permutation)]
        fixed = self._document["mc_design"]["kind"] == "fixed_n_categories"
        if fixed:
            if self._provider is None:
                denominator = float(self._d @ rates)
                jsnom = self._document["mc_design"]["kappa"]*(self._W*denominator-(self._W @ rates)[:, None]*self._d[None, :])/denominator**2
            jmc = np.eye(len(rates))*self._document["mc_design"]["total_groups"]
        else:
            if self._provider is None:
                jsnom = self._W
            jmc = np.diag([c["exposure"] for c in self._document["classes"]])
        if self._provider is None:
            signal = snom*factor
            main = b+mu*signal
            jmain = np.column_stack((signal, jb+mu*snom[:, None]*jfactor, mu*factor[:, None]*jsnom))
        else:
            jet = self._provider.jet(source_point, latent)
            main_values, main_jacobian = assemble_main_jet(b.tolist(), jb.tolist(), jet, mu)
            signal, main, jmain = np.array(jet["signal"]), np.array(main_values), np.array(main_jacobian)
        observations = self._observed if main_observations is None else main_observations
        if not isinstance(observations, list) or len(observations) != len(main):
            raise ValueError("complete source-ordered main observations required")
        observations = [_number(v, "main observation") for v in observations]
        if any(v < 0 for v in observations):
            raise ValueError("negative main observation")
        auxrows = self._source["retained_auxiliaries"]
        aux = [r["observed"] for r in auxrows] if source_auxiliary_observations is None else source_auxiliary_observations
        if not isinstance(aux, list) or len(aux) != len(auxrows):
            raise ValueError("complete retained source auxiliary observations required")
        dimension = 1+len(self._names)+len(rates)
        gradient = np.zeros(dimension)
        means, rows, terms = list(main), list(jmain), []

        def poisson_nll(n, mean):
            if mean < 0 or not math.isfinite(mean):
                raise ValueError("negative/nonfinite Poisson mean")
            if mean == 0:
                if n:
                    raise ValueError("zero probability: positive observation at zero expectation has no finite gradient")
                return 0., 1.
            return mean-n*math.log(mean)+math.lgamma(n+1), 1-n/mean

        for n, mean, row in zip(observations, main, jmain):
            term, slope = poisson_nll(n, float(mean))
            terms.append(term)
            gradient += slope*row
        for record, observed in zip(auxrows, aux):
            observed = _number(observed, "source auxiliary observation")
            index = 1+self._names.index(record["coordinate"])
            parameter = source_point[record["coordinate"]]
            row = np.zeros(dimension)
            if record["pdf"] == "normal":
                sigma = record["sigma"]
                terms.append(.5*((observed-parameter)/sigma)**2+math.log(sigma*math.sqrt(2*math.pi)))
                gradient[index] += (parameter-observed)/sigma**2
                means.append(parameter)
                row[index] = 1.
            else:
                if observed < 0:
                    raise ValueError("negative Poisson source auxiliary observation")
                mean = record["factor"]*parameter
                term, slope = poisson_nll(observed, mean)
                terms.append(term)
                gradient[index] += slope*record["factor"]
                means.append(mean)
                row[index] = record["factor"]
            rows.append(row)
        if fixed:
            terms.append(-math.lgamma(self._document["mc_design"]["total_groups"]+1))
        for i, (n, rate, mean) in enumerate(zip(counts, rates, nominal["mc_means"])):
            if fixed:
                if rate == 0 and n:
                    raise ValueError("zero probability: observed category with p zero")
                terms.append(math.lgamma(n+1)-(n*math.log(rate) if n else 0.))
                gradient[1+len(self._names)+i] += -n/rate if n else 0.
            else:
                term, slope = poisson_nll(n, mean)
                terms.append(term)
                gradient[1+len(self._names)+i] += slope*self._document["classes"][i]["exposure"]
            row = np.zeros(dimension)
            row[1+len(self._names):] = jmc[i]
            means.append(mean)
            rows.append(row)
        nll, jacobian = math.fsum(terms), np.array(rows)
        if not math.isfinite(nll) or any(not np.all(np.isfinite(v)) for v in (gradient, jacobian, signal, main)):
            raise ValueError("analytic joined density/gradient overflow")
        return {"nll":nll,"joint_logpdf":-nll,"finite":True,"gradient":gradient.tolist(),"distribution_mean_vector":list(map(float, means)),
                "distribution_mean_jacobian":jacobian.tolist(),"coordinate_order":["mu"]+["source:"+n for n in self._names]+["MC:"+n for n in self._class_ids],
                "source":{"main_means":main.tolist(),"background_means":b.tolist(),"signal_means":signal.tolist()},
                "gradient_scope":"Analytic admitted graph; fixed-N tangent mapping required; no clipping or zero-probability derivative", "physics_validated":False}

    def evaluate(self, source_point, latent, **kwargs):
        return self.evaluate_with_gradient(source_point, latent, **kwargs)



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


class AnalyticJointProfiler:
    def __init__(self,joint,background,mc,*,mu_domain,source_bound_semantics,rate_caps,max_free_dimension=256,fit_wall_seconds_limit=30):
        _keys(mu_domain,("initial","upper"),label="numerical mu search")
        if not 0<_number(mu_domain["initial"],"mu initial")<_number(mu_domain["upper"],"mu numerical upper")<=1000:raise ValueError("physical mu lower zero and explicit numerical upper required")
        if type(max_free_dimension) is not int or not 1<=max_free_dimension<=256:raise ValueError("analytic branch admits at most 256 explicitly budgeted free coordinates")
        if not isinstance(joint,AnalyticPublishedJoint):raise ValueError("qualified built-in analytic join required")
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
        if not 0<_number(fit_wall_seconds_limit,"fit wall limit")<=300:raise ValueError("explicit per-fit ceiling at most 300 seconds required")
        self._fit_wall_limit=fit_wall_seconds_limit
        self._mu=deepcopy(mu_domain);self._semantics=deepcopy(source_bound_semantics);self._caps=deepcopy(rate_caps);self._dimension=max_free_dimension

    def fit(self,*,fixed_mu=None,data=None,budget,fixed_source=None,fixed_latent=None,wall_hook=None):
        """Complete joint fit, or an explicitly labeled conditional subproblem.

        Only original source `fixed` flags are treated as genuine fixed model
        coordinates. Caller masks are retained separately and never relabeled
        as a full nuisance profile. Fixed-N optimization eliminates the last
        probability algebraically while preserving every category in density.
        """
        work=WorkBudget(budget,wall_hook,maximum_wall_seconds=self._fit_wall_limit);attempts=[];seed_records=[];starts=[];probe_refusals=[]
        if data is not None:
            data=self._joint.validate_data(data)
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
        if fixed_latent is not None:
            if self._joint._provider is None:self._mc.nominal(fixed_latent)
            else:self._mc.auxiliary_means(fixed_latent)
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
        if dimension>self._dimension:raise ValueError("admitted analytic dimension exceeded")
        T=np.zeros((len(classes),dimension));constant=np.zeros(len(classes))
        if fixed_latent is not None:constant=np.array([fixed_latent[c["id"]] for c in classes])
        else:
            for i in range(len(classes)-int(fixed_n)):T[i,latent_offset+i]=1.
            if fixed_n:T[-1,latent_offset:]=-1.;constant[-1]=1.
        W=np.array([c["contribution"] for c in classes]).T
        rows=list(W@T);intercepts=list(W@constant);labels=[{"kind":"net","bin":b["id"],"physical":True} for b in self._mc_document["bins"]]
        if self._joint._provider is not None:
            # Reference-template positivity is not a physical constraint on a
            # transported absolute response at a different nuisance point.
            # Its complete current signal/background constraints are below.
            rows=[];intercepts=[];labels=[]
        relative_denominator=None
        if fixed_n:
            d=np.array([c["denominator_mark"] for c in classes])
            if self._joint._provider is not None:
                relative_denominator=relative_denominator_domain(d.tolist(),denominator_floor=floor)
                d=np.array(relative_denominator["denominator_row"])
            rows.append(d@T);intercepts.append(float(d@constant)-floor);labels.append({"kind":"denominator_floor","physical":False})
            if relative_denominator is not None:labels[-1].update(relative_to_max_abs_mark=True,denominator_scale=relative_denominator["denominator_scale"])
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
                "numerical_floors":{"positive_observation_rate_or_probability":floor,"expected_denominator":floor},"numerical_rate_caps":deepcopy(self._caps),"numerical_mu_cap":self._mu["upper"],"derivative_backend":"qualified analytic NumPy pyhf0.7.6 graph","nonlinear_physical_constraints":"aggregate source background and non-MC signal nonnegative","joint_contract_sha256":self._joint.contract_sha256}
        if self._joint._provider is not None:
            recipe["derivative_backend"]="explicit_complete_marked_response_analytic_provider"
            recipe["nonlinear_physical_constraints"]="aggregate source background and absolute transported signal with source+MC columns"
            recipe["response_provider_contract"]=self._joint._provider.contract()
            recipe["relative_denominator_search_domain"]=deepcopy(relative_denominator)
            recipe["numerical_floors"]["expected_denominator"]=None
            recipe["numerical_floors"]["relative_expected_denominator"]=floor
        def finish(**fields):
            return {"verified":False,"attempts":attempts,"planned_start_count":len(starts),"unlaunched_start_count":max(0,len(starts)-len(attempts)),"start_generation":seed_records,"density_probe_refusals":probe_refusals,"recipe":recipe,"work":work.snapshot(),"physics_validated":False,"global_optimum_certified":False,
                    "scope":"Bounded analytic numerical joint profiling evidence; no globality, coverage, CLs or exclusion claim",**fields}
        selected=self._joint.supported_mc_categories()
        if fixed_mu is None and fixed_latent is None and all(counts[i]==0 for i in selected):
            return finish(status="unresolved_strength_recession",failure="all nominal selected MC categories observed zero: finite strength endpoint not established; source-dependent marked response can require additional recession analysis")
        def evaluation(x):
            work.charge("objective_calls");p=parameters(np.asarray(x))
            if any(not lo-1e-14<=v<=hi+1e-14 for v,(lo,hi) in zip(x,bounds)) or np.any(G@x+h<-1e-12):return None
            try:
                work.charge("gradient_calls") # complete density/Jacobian pass
                result=self._joint.evaluate_with_gradient(p["source"],p["latent"],mu=p["mu"],**supplied)
            except (ValueError,OverflowError,FloatingPointError) as error:
                if len(probe_refusals)<16:probe_refusals.append({"coordinates":list(map(float,x)),"kind":type(error).__name__,"error":str(error)})
                return None
            work.check()
            if not result["finite"]:
                if len(probe_refusals)<16:probe_refusals.append({"coordinates":list(map(float,x)),"kind":"zero_probability"})
                return None
            # Chain the full analytic columns into the exact optimization
            # coordinates, including the eliminated last probability.
            full_axes=result["coordinate_order"]
            projection=np.zeros((len(full_axes),dimension))
            for i,name in enumerate(axes[:latent_offset]):projection[full_axes.index(name),i]=1.
            projection[1+len(self._source["active_parameter_names"]):,:]=T
            gradient=np.asarray(result["gradient"])@projection
            jacobian=np.asarray(result["distribution_mean_jacobian"])@projection
            work.check()
            return result["nll"],np.asarray(result["distribution_mean_vector"]),gradient,jacobian
        def objective(x):
            result=evaluation(x);return math.inf if result is None else result[0]
        def derivatives(x):
            result=evaluation(x)
            if result is None:raise ValueError("analytic derivative requested at nonfinite/infeasible point")
            return result[2],result[3]
        def source_constraints(x,gradient=False):
            if not gradient:work.charge("objective_calls")
            work.charge("gradient_calls") # graph computes values and Jacobian together
            p=parameters(x)
            values,jac=self._joint.physical_constraints_at(p["source"],p["latent"])
            projection=np.zeros((len(self._source["active_parameter_names"])+len(classes),dimension))
            for i,name in enumerate(source_axes):projection[self._source["active_parameter_names"].index(name),int(fixed_mu is None)+i]=1.
            projection[len(self._source["active_parameter_names"]):,:]=T
            work.check()
            return jac@projection if gradient else values
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
                                    constraints=[{"type":"ineq","fun":lambda x:G@x+h,"jac":lambda x:G},{"type":"ineq","fun":source_constraints,"jac":lambda x:source_constraints(x,True)}],method="SLSQP",options={"maxiter":budget["maxiter"],"ftol":1e-10})
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
                source_values=source_constraints(x)
                witness["nonlinear_constraints"]={"residuals":_diagnostic_values(source_values),
                    "labels":[{"kind":"source_background_nonnegative" if i<len(source_values)//2 else "source_signal_nonnegative",
                               "bin":i%(len(source_values)//2),"physical":True} for i in range(len(source_values))]}
                source_rows=source_constraints(x,True)
                witness["nonlinear_constraints"]["jacobian"]=_diagnostic_values(source_rows)
                for i,(row,residual) in enumerate(zip(source_rows,source_values)):
                    if _tangent_active(float(residual),1e-7*max(1.,float(np.linalg.norm(row))),physical=True):linear.append(-row);active.append({"kind":"source_background_nonnegative" if i<len(source_values)//2 else "source_signal_nonnegative","bin":i%(len(source_values)//2),"physical":True})
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
        WorkBudget(budget_per_fit,maximum_wall_seconds=self._fit_wall_limit) # validate the complete per-fit budget early
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
