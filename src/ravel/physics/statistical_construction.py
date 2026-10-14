"""Question-directed regional count-model construction, without a fitting engine.

The supplied law is a product of disjoint-bin Poissons and one explicitly supplied
Gaussian auxiliary block. Signed terms enter the TOTAL mean, not independent
Poissons. Transfer and ABCD helpers only construct declared algebra. No data table
implies disjointness, MC law, closure, covariance or EFT applicability.
"""
from __future__ import annotations

import copy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from ravel.physics.eft_functions import rational
from ravel.physics import parametric_shapes, continuous_dijet_shapes

KIND = "regional-poisson-construction/v1"
IDENT = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}\Z")


def _keys(obj, keys, name):
    if type(obj) is not dict or set(obj) != set(keys):
        raise ValueError(name + " requires exactly " + ", ".join(sorted(keys)))


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("bounded nonempty " + name + " required")
    return value


def _id(value):
    if not isinstance(value, str) or not IDENT.fullmatch(value) or value in {"MH", "ModelConfig", "ModelConfig_bonly", "data_obs", "w"} or value.startswith(("ravel_", "CMS_", "n_exp_", "n_obs_")):
        raise ValueError("nonreserved native identifier required")
    return value


def _q(value):
    q = rational(value)
    f = float(q)
    if not math.isfinite(f) or q != 0 and f == 0:
        raise ValueError("coefficient must have finite nonzero binary64 representation")
    return q


def _vector(values, n, name):
    if type(values) is not list or len(values) != n:
        raise ValueError("complete ordered " + name + " required")
    return [_q(v) for v in values]


def _bounds(values, initial):
    lo, hi = _vector(values, 2, "bounds")
    if not lo < hi or not float(lo) < float(hi) or not lo <= _q(initial) <= hi:
        raise ValueError("ordered explicit bounds containing initial value required")
    return lo, hi


def _native_namespace(document):
    """Validate the generated Combine 9.2.1 counting-model namespace.

    This is the closed emitted card/plugin route: two fixed processes, param
    Gaussian auxiliaries, optional flatParam physical coordinates, no shapes,
    rateParams, nuisance groups, external functions or arbitrary builder flags.
    Source-only auxiliary names are substituted algebraically, not RooAbsArgs.
    Internal names are reserved even when a particular empty set is omitted.
    """
    roster = {}
    def add(name, purpose):
        if name in roster:
            raise ValueError("native namespace collision: " + name + " (" + roster[name] + "; " + purpose + ")")
        roster[name] = purpose
    for name in ("w", "MH", "ModelConfig", "ModelConfig_bonly", "data_obs",
                 "POI", "observables", "nuisances", "globalObservables",
                 "discreteParams", "nuisancePdf", "model_s", "model_b"):
        add(name, "Combine infrastructure")
    for row in document["parameters"]:
        add(row["name"], "physical coordinate")
    k = len(document["auxiliary"]["names"])
    for i in range(k):
        for suffix in ("", "_In", "_Pdf"):
            add("ravel_aux_" + str(i) + suffix, "Gaussian auxiliary")
    for t, term in enumerate(document["terms"]):
        if "shape" in term:
            if term["shape"]["kind"] == continuous_dijet_shapes.KIND:
                for suffix in ("integral_full", *["parameter_"+str(i) for i in range(len(term["shape"]["parameters"]))]):
                    add("ravel_shape_"+str(t)+"_"+suffix, "continuous dijet integral")
                for b,w in enumerate(term["shape"]["bin_windows"]):
                    if w is not None and _q(term["coefficients"][b]):
                        add("ravel_shape_"+str(t)+"_integral_"+str(b), "continuous dijet numerator")
            for suffix in ("x", "slope", "pdf"):
                add("ravel_shape_" + str(t) + "_" + suffix, "exponential density")
            for b, w in enumerate(term["shape"]["bin_windows"]):
                if w is not None and _q(term["coefficients"][b]):
                    add("ravel_fraction_" + str(b) + "_" + str(t), "normalized exponential integral")
    for b, row in enumerate(document["bins"]):
        ident = row["id"]
        add("n_obs_bin" + ident, "count observation " + ident)
        for process in ("ravel_full", "ravel_dummy"):
            add("n_exp_bin" + ident + "_proc_" + process, "process expectation " + ident)
        for suffix in ("", "_bonly"):
            add("n_exp_bin" + ident + suffix, "total expectation " + ident)
            add("pdf_bin" + ident + suffix, "count PDF " + ident)
        add("ravel_mean_" + str(b), "full signed mean " + ident)
        for t, term in enumerate(document["terms"]):
            if _q(term["coefficients"][b]):
                add("ravel_term_" + str(b) + "_" + str(t), "supplied mean term " + ident)
    # DatacardParser adds param nuisances to systs, but not flatParam without
    # --X-assign-flatParam-prior; that option is absent from this closed route.
    prefix = "modelObs" if k else "model"
    if k:
        add("modelObs_s", "constrained observation product")
        add("modelObs_b", "constrained observation product")
    if len(document["bins"]) > 50:
        for i in range((len(document["bins"]) + 9) // 10):
            for side in ("s", "b"):
                add(prefix + "_" + side + "_" + str(i), "blocked observation product")
    return roster


def validate(document):
    """Validate an explicit supplied law; never infer it from observed tables."""
    if len(json.dumps(document, allow_nan=False).encode()) > 4 * 1024 * 1024:
        raise ValueError("construction document exceeds 4 MiB source bound")
    _keys(document, {"schema_version", "model_id", "question", "sources", "parameters", "bins", "terms", "auxiliary", "partition", "prediction", "template_statistics", "assumptions"} | ({"expected_data"} if "expected_data" in document else set()), "regional construction")
    if type(document["schema_version"]) is not int or document["schema_version"] != 1:
        raise ValueError("regional construction schema 1 required")
    _id(document["model_id"]); _text(document["question"], "question")
    sources = document["sources"]
    if type(sources) is not list or not 1 <= len(sources) <= 128:
        raise ValueError("bounded nonempty source population required")
    source_ids = set()
    for row in sources:
        _keys(row, {"id", "path", "sha256"}, "source")
        name = _id(row["id"]); _text(row["path"], "source path")
        if name in source_ids or not isinstance(row["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"]):
            raise ValueError("unique source identities with SHA256 required")
        source_ids.add(name)
    def source(value):
        if value not in source_ids:
            raise ValueError("unbound scientific source")
    pars = document["parameters"]
    if type(pars) is not list or not 1 <= len(pars) <= 128:
        raise ValueError("bounded physical parameter population required")
    names, pois = set(), []
    for row in pars:
        _keys(row, {"name", "role", "initial", "bounds", "fixed", "meaning", "source"}, "parameter")
        name = _id(row["name"])
        if name in names or row["role"] not in ("poi", "rate", "coefficient") or type(row["fixed"]) is not bool:
            raise ValueError("unique typed physical parameters required")
        names.add(name); source(row["source"]); _text(row["meaning"], "parameter meaning")
        lo, _ = _bounds(row["bounds"], row["initial"])
        if row["role"] == "rate" and lo < 0:
            raise ValueError("rate domain must be nonnegative")
        if row["role"] == "poi":
            pois.append(name)
            if row["fixed"]:
                raise ValueError("profile POI cannot be fixed")
    if len(pois) != 1:
        raise ValueError("exactly one profile POI required; other coefficients may float")
    bins = document["bins"]
    if type(bins) is not list or not 1 <= len(bins) <= 256:
        raise ValueError("bounded complete SR/CR bin population required")
    ids, observations = set(), set()
    for row in bins:
        _keys(row, {"id", "role", "observed", "observation_id", "source"}, "bin")
        name = _id(row["id"]); _text(row["observation_id"], "observation identity")
        if name in ids or row["observation_id"] in observations or row["role"] not in ("signal_region", "control_region", "mc_auxiliary") or not (("expected_data" in document and document["expected_data"].get("conditioning")=="supplied_nominal" and row["observed"] is None) or (type(row["observed"]) is int and row["observed"]>=0)): 
            raise ValueError("unique complete integer count observations and SR/CR roles required")
        ids.add(name); observations.add(row["observation_id"]); source(row["source"])
    partition = document["partition"]
    _keys(partition, {"kind", "source", "statement"}, "partition")
    if partition["kind"] != "declared_disjoint_poisson_counts":
        raise ValueError("overlapping/weighted observations need a separately supplied likelihood")
    source(partition["source"]); _text(partition["statement"], "partition evidence/assumption")
    aux = document["auxiliary"]
    _keys(aux, {"kind", "names", "observed", "factor", "eta_bounds", "source"}, "auxiliary")
    if aux["kind"] != "supplied_gaussian_factor" or type(aux["names"]) is not list or len(aux["names"]) > 32 or len(set(aux["names"])) != len(aux["names"]):
        raise ValueError("one explicit bounded Gaussian factor law required")
    for name in aux["names"]:
        _id(name)
        if name in names:
            raise ValueError("physical and auxiliary coordinate names must be disjoint")
    source(aux["source"])
    k = len(aux["names"])
    _vector(aux["observed"], k, "auxiliary observations")
    if type(aux["factor"]) is not list or len(aux["factor"]) != k or type(aux["eta_bounds"]) is not list or len(aux["eta_bounds"]) != k:
        raise ValueError("complete supplied lower factor and native-coordinate domain required")
    for i, row in enumerate(aux["factor"]):
        values = _vector(row, k, "Gaussian factor")
        if values[i] <= 0 or any(values[j] for j in range(i + 1, k)):
            raise ValueError("positive-diagonal lower triangular supplied factor required")
        lo, hi = _bounds(aux["eta_bounds"][i], "0")
        if not lo < 0 < hi:
            raise ValueError("auxiliary native domain must contain observed zero in its interior")
    terms = document["terms"]
    if type(terms) is not list or not 1 <= len(terms) <= 1024:
        raise ValueError("bounded complete mean decomposition required")
    term_ids, used = set(), set()
    for row in terms:
        _keys(row, {"id", "basis", "coefficients", "powers", "log_response", "source"} | ({"shape"} if "shape" in row else set()), "mean term")
        name = _id(row["id"])
        if name in term_ids or row["basis"] not in ("background", "sm", "bsm", "interference", "full"):
            raise ValueError("unique mean term and explicit physical basis required")
        term_ids.add(name); source(row["source"])
        _vector(row["coefficients"], len(bins), "all-bin coefficients including zero control contamination")
        if type(row["powers"]) is not dict or set(row["powers"]) - (names | set(aux["names"])) or any(type(v) is not int or not 1 <= v <= 6 for v in row["powers"].values()) or sum(row["powers"].values()) > 12:
            raise ValueError("bounded integer monomials in declared parameters required")
        used.update(row["powers"])
        if "shape" in row:
            if row["shape"]["kind"] == continuous_dijet_shapes.KIND:
                _, windows = continuous_dijet_shapes.validate(row["shape"],pars,aux,len(bins))
            else:
                _, windows = parametric_shapes.validate(row["shape"],pars,aux,len(bins))
            if row["basis"] != "background" or any(_q(c) < 0 for c in row["coefficients"]):
                raise ValueError("normalized parametric component must be nonnegative background")
            if any(w is None and _q(c) for w,c in zip(windows,row["coefficients"])) or not any(w is not None and _q(c) for w,c in zip(windows,row["coefficients"])):
                raise ValueError("shape support must match explicit absent coefficients")
            if row["shape"]["kind"] == continuous_dijet_shapes.KIND:
                used.update(row["shape"]["parameters"])
            else:
                used.add(parametric_shapes.parameter(row["shape"]))
        if type(row["log_response"]) is not list or len(row["log_response"]) != len(bins):
            raise ValueError("complete all-bin log response required")
        for values in row["log_response"]:
            _vector(values, k, "shared nuisance response")
    if names - used:
        raise ValueError("unused physical parameters obscure the requested fit")
    pred = document["prediction"]
    _keys(pred, {"units", "energy", "luminosity", "basis", "scale", "domain_statement", "source"}, "prediction context")
    for key in ("units", "energy", "luminosity", "basis", "scale", "domain_statement"):
        _text(pred[key], key)
    if pred["units"] != "expected_events":
        raise ValueError("coefficients must already be normalized expected-event contributions")
    source(pred["source"])
    stats = document["template_statistics"]
    explicit_mc = stats.get("kind") == "explicit_independent_poisson_auxiliary"
    _keys(stats, {"kind", "statement", "source"} | ({"experiments", "independence"} if explicit_mc else set()), "template sampling law")
    mc_bins = {b["id"] for b in bins if b["role"] == "mc_auxiliary"}
    if explicit_mc:
        _text(stats["independence"], "supplied independence of unweighted MC experiments and data")
        experiments = stats["experiments"]
        if type(experiments) is not list or not 1 <= len(experiments) <= 64:
            raise ValueError("complete bounded MC auxiliary population required")
        seen_bins, seen_rates = set(), set()
        for e in experiments:
            _keys(e, {"bin", "rate", "exposure", "source"}, "MC auxiliary experiment")
            source(e["source"])
            p = next((p for p in pars if p["name"] == e["rate"]), None)
            if e["bin"] not in mc_bins or e["bin"] in seen_bins or e["rate"] in seen_rates or p is None or p["role"] != "rate" or _q(e["exposure"]) <= 0:
                raise ValueError("unique MC bin/rate and positive supplied exposure required")
            seen_bins.add(e["bin"]); seen_rates.add(e["rate"])
            i = next(i for i,b in enumerate(bins) if b["id"] == e["bin"])
            active = [t for t in terms if _q(t["coefficients"][i])]
            if len(active) != 1 or active[0]["powers"] != {e["rate"]:1} or _q(active[0]["coefficients"][i]) != _q(e["exposure"]) or any(_q(v) for v in active[0]["log_response"][i]) or "shape" in active[0] or active[0]["basis"] != "background" or active[0]["source"] != e["source"]:
                raise ValueError("MC auxiliary mean must be exactly exposure times shared latent rate")
            if not any(e["rate"] in t["powers"] and any(_q(t["coefficients"][j]) for j,b in enumerate(bins) if b["role"] != "mc_auxiliary") for t in terms):
                raise ValueError("MC rate must inform an actual main SR/CR mean")
        if seen_bins != mc_bins:
            raise ValueError("every MC observation needs its supplied experiment")
    elif stats["kind"] != "conditional_on_supplied_coefficients" or mc_bins:
        raise ValueError("weighted/signed MC laws require their existing explicit auxiliary consumer; no automatic Gaussianization")
    source(stats["source"]); _text(stats["statement"], "template sampling statement")
    if type(document["assumptions"]) is not list or not document["assumptions"]:
        raise ValueError("at least one explicit source/physical applicability assumption required")
    for row in document["assumptions"]:
        _keys(row, {"id", "statement", "source", "status"}, "assumption")
        _id(row["id"]); _text(row["statement"], "assumption"); source(row["source"])
        if row["status"] not in ("assumed", "externally_checked"):
            raise ValueError("explicit assumption status required")
    _native_namespace(document)
    if "expected_data" in document:
        from ravel.physics import regional_expected
        regional_expected.validate(document)
    return copy.deepcopy(document)


def source_inputs(document, base, *, _session=None):
    from ravel.workflow.science import regular
    validate(document)
    result = []
    for row in document["sources"]:
        p = regular(row["path"], base, _session=_session)
        digest = _session.hash_file(p) if _session else hashlib.sha256(p.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            raise ValueError("construction source changed: " + row["id"])
        result.append(p)
    return list(dict.fromkeys(result))


def poisson_template_auxiliary(document, experiments, *, statement, independence, source):
    """Add supplied unweighted Poisson MC experiments to the SAME complete law.

    m_j ~ Poisson(exposure_j*rate_j), with that rate already used in main SR/CR
    means. This is an explicit Poissonized normalization experiment, not fixed
    total multinomial marks, weighted events, or shape errors inferred from sumw2.
    No second constraint on the rates is inferred or added automatically.
    """
    d = validate(document)
    if d['template_statistics']['kind'] != 'conditional_on_supplied_coefficients':
        raise ValueError('MC experiments already present; duplicate attachment refused')
    _text(statement,'MC sampling statement'); _text(independence,'MC independence statement')
    if source not in {r['id'] for r in d['sources']} or type(experiments) is not list or not 1 <= len(experiments) <= 64:
        raise ValueError('supplied bounded MC population and bound source required')
    mappings = []; original_n = len(d['bins']); k = len(d['auxiliary']['names'])
    for e in experiments:
        _keys(e, {'bin','rate','exposure','source','observed','observation_id'},'MC count input')
        _id(e['bin'])
        if type(e['observed']) is not int or e['observed'] < 0:
            raise ValueError('literal nonnegative unweighted MC counts required')
        d['bins'].append({'id':e['bin'],'role':'mc_auxiliary','observed':e['observed'],
                          'observation_id':e['observation_id'],'source':e['source']})
        mappings.append({key:e[key] for key in ('bin','rate','exposure','source')})
    for t in d['terms']:
        t['coefficients'].extend(['0']*len(experiments)); t['log_response'].extend([['0']*k for _ in experiments])
        if 'shape' in t:
            t['shape']['bin_windows'].extend([None]*len(experiments))
    for j,e in enumerate(experiments):
        cs = ['0']*len(d['bins']); cs[original_n+j] = e['exposure']
        d['terms'].append({'id':e['bin']+'_auxiliary','basis':'background','coefficients':cs,
                          'powers':{e['rate']:1},'log_response':[['0']*k for _ in d['bins']],'source':e['source']})
    d['template_statistics'] = {'kind':'explicit_independent_poisson_auxiliary','statement':statement,
                               'source':source,'experiments':mappings,'independence':independence}
    return validate(d)


def coordinates(document):
    d = validate(document)
    return [p["name"] for p in d["parameters"]] + ["ravel_aux_" + str(i) for i in range(len(d["auxiliary"]["names"]))]


def mean_jet(document, point):
    """Pure supplied algebra and first derivatives. No density or optimizer call.

    Full point population required; signed pieces are retained before TOTAL-mean
    domain classification. Fraction monomials avoid cancellation before exp.
    """
    d = validate(document); names = coordinates(d)
    if type(point) is not dict or set(point) != set(names):
        raise ValueError("complete physical plus whitened auxiliary point required")
    q = {key: _q(value) for key, value in point.items()}
    for p in d["parameters"]:
        if not _q(p["bounds"][0]) <= q[p["name"]] <= _q(p["bounds"][1]) or p["fixed"] and q[p["name"]] != _q(p["initial"]):
            raise ValueError("point violates physical bound/fixed value")
    aux = d["auxiliary"]; k = len(aux["names"])
    eta = [q["ravel_aux_" + str(i)] for i in range(k)]
    for v, bounds in zip(eta, aux["eta_bounds"]):
        if not _q(bounds[0]) <= v <= _q(bounds[1]):
            raise ValueError("point violates explicit auxiliary domain")
    theta = [_q(aux["observed"][i]) + sum((_q(aux["factor"][i][j]) * eta[j] for j in range(k)), Fraction()) for i in range(k)]
    values = {**q, **dict(zip(aux["names"], theta))}
    means, jac, pieces = [], [], []
    shape_values = {}
    for t, term in enumerate(d["terms"]):
        if "shape" in term:
            if term["shape"]["kind"] == continuous_dijet_shapes.KIND:
                effective = continuous_dijet_shapes.effective_parameters(term["shape"],values,theta)
                shape_values[t] = continuous_dijet_shapes.fractions(term["shape"],effective)
            else:
                slope = parametric_shapes.effective_slope(term["shape"],values,theta)
                shape_values[t] = parametric_shapes.fractions(term["shape"],slope)
    for b in range(len(d["bins"])):
        terms, derivs = [], [[] for _ in names]
        for t, term in enumerate(d["terms"]):
            coefficient = _q(term["coefficients"][b]); powers = term["powers"]
            if not coefficient:
                terms.append(0.0)
                for values_ in derivs: values_.append(0.0)
                continue
            monomial = coefficient * math.prod(values[name] ** power for name, power in powers.items())
            r = [_q(x) for x in term["log_response"][b]]
            exponent = sum((r[i] * theta[i] for i in range(k)), Fraction())
            weight = math.exp(float(exponent))
            fraction, fraction_derivative = (shape_values[t][0][b],shape_values[t][1][b]) if t in shape_values else (1.,0.)
            value = float(monomial) * weight * fraction
            terms.append(value)
            for index, name in enumerate(names):
                derivative = Fraction()
                exponent_derivative, slope_derivative = Fraction(), Fraction()
                if name in powers:
                    derivative = coefficient * powers[name] * math.prod(values[n] ** (power - (n == name)) for n, power in powers.items())
                if index >= len(d["parameters"]):
                    j = index-len(d["parameters"])
                    exponent_derivative = sum((r[i]*_q(aux["factor"][i][j]) for i in range(k)),Fraction())
                    derivative += sum((coefficient*powers[a]*math.prod(values[n]**(power-(n == a)) for n,power in powers.items())*_q(aux["factor"][i][j]) for i,a in enumerate(aux["names"]) if a in powers),Fraction())
                    if t in shape_values and term["shape"]["kind"] != continuous_dijet_shapes.KIND:
                        slope_derivative = sum((_q(parametric_shapes.parameter_response(term["shape"])[i])*_q(aux["factor"][i][j]) for i in range(k)),Fraction())
                elif t in shape_values and term["shape"]["kind"] != continuous_dijet_shapes.KIND and name == parametric_shapes.parameter(term["shape"]):
                    slope_derivative = Fraction(1)
                shape_derivative = continuous_dijet_shapes.coordinate_gradient(term["shape"],fraction_derivative,name,aux) if t in shape_values and term["shape"]["kind"] == continuous_dijet_shapes.KIND else fraction_derivative*float(slope_derivative)
                derivs[index].append(float(derivative)*weight*fraction + value*float(exponent_derivative) + float(monomial)*weight*shape_derivative)
        means.append(math.fsum(terms)); pieces.append(terms)
        jac.append([math.fsum(values) for values in derivs])
    if not all(math.isfinite(v) for v in means + [x for row in jac for x in row] + [x for row in pieces for x in row]):
        raise ValueError("nonfinite supplied mean/derivative arithmetic")
    return {"coordinates": names, "bins": [b["id"] for b in d["bins"]], "means": means, "jacobian": jac,
            "term_order": [t["id"] for t in d["terms"]], "term_values": pieces,
            "strictly_positive_total": all(v > 0 for v in means), "clipping_applied": False}


def initial_point(document):
    d = validate(document)
    return {**{p["name"]: p["initial"] for p in d["parameters"]}, **{"ravel_aux_" + str(i): "0" for i in range(len(d["auxiliary"]["names"]))}}


def transfer_terms(bin_ids, latent_names, matrix, *, source, auxiliary_count=0, prefix="transfer"):
    """Supplied complete transfer matrix times shared latent rates; no fitted ratios."""
    if not bin_ids or len(set(bin_ids)) != len(bin_ids) or not latent_names or len(set(latent_names)) != len(latent_names):
        raise ValueError("complete unique transfer bins and latent coordinates required")
    for name in [*bin_ids, *latent_names, prefix]: _id(name)
    if type(auxiliary_count) is not int or not 0 <= auxiliary_count <= 32 or type(matrix) is not list or len(matrix) != len(bin_ids):
        raise ValueError("complete transfer dimensions required")
    rows = [_vector(row, len(latent_names), "transfer matrix") for row in matrix]
    if any(x < 0 for row in rows for x in row):
        raise ValueError("transfer coefficients must be nonnegative; signed terms use explicit polynomial construction")
    return [{"id": prefix + "_" + str(j), "basis": "background", "coefficients": [str(row[j]) for row in rows],
             "powers": {name: 1}, "log_response": [["0"] * auxiliary_count for _ in rows], "source": source} for j, name in enumerate(latent_names)]


def abcd_terms(bin_ids, regions, *, beta, x, y, closure, source, auxiliary_count=0, prefix="abcd"):
    """A=beta*x*y*closure, B=beta*x, C=beta*y, D=beta.

    Complete control contamination is added via ordinary all-bin signal terms.
    Closure is a declared parameter (fixed or constrained through caller terms),
    never an uncertainty inferred from ABCD geometry. Zero beta uses no division.
    """
    _keys(regions, {"A", "B", "C", "D"}, "ABCD map")
    if len(set(regions.values())) != 4 or set(regions.values()) - set(bin_ids) or len(set(bin_ids)) != len(bin_ids) or len({beta, x, y, closure}) != 4:
        raise ValueError("four distinct included regions and four distinct parameters required")
    for name in [*bin_ids, beta, x, y, closure, prefix]: _id(name)
    if type(auxiliary_count) is not int or not 0 <= auxiliary_count <= 32:
        raise ValueError("bounded auxiliary dimension required")
    powers = {"A": {beta: 1, x: 1, y: 1, closure: 1}, "B": {beta: 1, x: 1}, "C": {beta: 1, y: 1}, "D": {beta: 1}}
    return [{"id": prefix + "_" + key, "basis": "background", "coefficients": ["1" if b == regions[key] else "0" for b in bin_ids],
             "powers": value, "log_response": [["0"] * auxiliary_count for _ in bin_ids], "source": source} for key, value in powers.items()]


def _native_number(value):
    return format(float(_q(value)), ".17g")


def _formula_number(value):
    q = _q(value)
    # Floating tokens prevent C++ integer division; exact original remains in IR.
    return "(" + _native_number(str(q.numerator)) + "/" + _native_number(str(q.denominator)) + ".0)" if q.denominator != 1 and abs(q.denominator) < 10**15 else _native_number(value)


def response(document):
    """Closed native lowering. No interpolation/Poisson/sampling assumptions added."""
    d = validate(document); names = coordinates(d); aux = d["auxiliary"]; k = len(aux["names"])
    factories, functions = [], {}
    shape_factories, shape_observables, shape_integrals = [], [], []
    for t, term in enumerate(d["terms"]):
        if "shape" not in term:
            continue
        shape = term["shape"]
        if shape["kind"] == continuous_dijet_shapes.KIND:
            variable,density,integrals = continuous_dijet_shapes.native_payload(shape,t,names,aux,term["coefficients"])
            shape_observables.append(variable); shape_factories.extend(density); shape_integrals.append(integrals)
            continue
        power = shape['kind'] == 'normalized_power'
        width, windows = (parametric_shapes.power_geometry if power else parametric_shapes.geometry)(shape["domain"],shape["bin_windows"])
        prefix = "ravel_shape_"+str(t)
        shape_observables.append(prefix+"_x[0.5,0,1]")
        r = list(map(_q,parametric_shapes.parameter_response(shape)))
        offset = sum((r[i]*_q(aux["observed"][i]) for i in range(k)),Fraction())
        slopes = [sum((r[i]*_q(aux["factor"][i][j]) for i in range(k)),Fraction()) for j in range(k)]
        expression = _formula_number(str(width))+"*(@"+str(names.index(parametric_shapes.parameter(shape)))+"+"+_formula_number(str(offset+(1 if power else 0)))+"".join("+("+_formula_number(str(v))+")*@"+str(len(d["parameters"])+j) for j,v in enumerate(slopes) if v)+")"
        shape_factories.append('expr::'+prefix+'_slope("'+expression+'",'+','.join(names)+')')
        shape_factories.append('Exponential::'+prefix+'_pdf('+prefix+'_x,'+prefix+'_slope)')
        for b,w in enumerate(windows):
            if w is not None and _q(term["coefficients"][b]):
                expression = parametric_shapes.native_power_fraction_expression(shape,b,width,w) if power else parametric_shapes.native_fraction_expression(w)
                shape_factories.append('expr::ravel_fraction_'+str(b)+'_'+str(t)+'("'+expression+'",'+prefix+'_slope)')
    for b, row in enumerate(d["bins"]):
        term_names = []
        for t, term in enumerate(d["terms"]):
            if not _q(term["coefficients"][b]):
                continue
            expression = _formula_number(term["coefficients"][b])
            for name, power in term["powers"].items():
                if name in aux["names"]:
                    i = aux["names"].index(name)
                    argument = _formula_number(aux["observed"][i]) + "".join("+(" + _formula_number(aux["factor"][i][j]) + ")*@" + str(len(d["parameters"]) + j) for j in range(k) if _q(aux["factor"][i][j]))
                    argument = "(" + argument + ")"
                else:
                    argument = "@" + str(names.index(name))
                expression += "*pow(" + argument + "," + str(power) + ")"
            r = [_q(v) for v in term["log_response"][b]]
            offset = sum((r[i] * _q(aux["observed"][i]) for i in range(k)), Fraction())
            slopes = [sum((r[i] * _q(aux["factor"][i][j]) for i in range(k)), Fraction()) for j in range(k)]
            if offset or any(slopes):
                expression += "*exp(" + _formula_number(str(offset)) + "".join("+(" + _formula_number(str(slope)) + ")*@" + str(len(d["parameters"]) + j) for j, slope in enumerate(slopes) if slope) + ")"
            name = "ravel_term_" + str(b) + "_" + str(t)
            args = list(names)
            if "shape" in term:
                expression += "*@"+str(len(args)); args.append("ravel_fraction_"+str(b)+"_"+str(t))
            factories.append('expr::' + name + '("' + expression + '",' + ','.join(args) + ')'); term_names.append(name)
        if not term_names:
            raise ValueError("structurally zero full mean is unsupported by this strict-positive native route")
        fn = "ravel_mean_" + str(b)
        factories.append("sum::" + fn + "(" + ",".join(term_names) + ")")
        functions[fn] = {"bin": row["id"]}
    if any(len(expr) > 20000 for expr in shape_factories + factories) or sum(len(expr) for expr in shape_factories + factories) > 4 * 1024 * 1024:
        raise ValueError("native construction formulas exceed bounded source envelope")
    poi = next(p for p in d["parameters"] if p["role"] == "poi")
    additions = {"shape_factories":shape_factories,"shape_observables":shape_observables} if shape_factories else {}
    if shape_integrals:
        additions["shape_integrals"] = shape_integrals
    return {"kind": KIND, "document": d, "coordinates": names, "factories": factories, "functions": functions, **additions,
            "domain": {"name": poi["name"], "lower": poi["bounds"][0], "upper": poi["bounds"][1]},
            "law": {"mean": "sum of signed terms, without clipping", "auxiliary": "one supplied Gaussian factor; theta=z+L*eta, eta observation 0",
                    "absolute_nll_offset": "Original physical auxiliary NLL minus whitened normalized auxiliary NLL is sum(log(diag(L))); native raw NLL may additionally omit constants",
                    "domain": "all declared coordinate bounds AND every full mean strictly positive; native optimizer domain behavior requires qualification",
                    "finite_mc": (copy.deepcopy(d["template_statistics"]) if d["template_statistics"]["kind"] == "explicit_independent_poisson_auxiliary" else "conditional on supplied coefficients; no MC uncertainty inferred"),
                    "supplied_auxiliary_covariance": [[str(sum((_q(aux["factor"][i][a]) * _q(aux["factor"][j][a]) for a in range(k)), Fraction())) for j in range(k)] for i in range(k)],
                    "coverage_qualified": False}}


def datacard(document):
    d = validate(document); bins = [b["id"] for b in d["bins"]]
    lines = ["# Full regional mean. Dummy signal is identically zero; no model_b interpretation.",
             "imax " + str(len(bins)), "jmax 1", "kmax *", "------------",
             "bin " + " ".join(bins), "observation " + " ".join(str(0 if b["observed"] is None else b["observed"]) for b in d["bins"]), "------------",
             "bin " + " ".join(b for b in bins for _ in range(2)),
             "process " + " ".join(["ravel_full ravel_dummy"] * len(bins)),
             "process " + " ".join(["1 0"] * len(bins)),
             "rate " + " ".join(["1 0"] * len(bins)), "------------"]
    for p in d["parameters"]:
        if p["role"] != "poi" and not p["fixed"]:
            lines.append(p["name"] + " flatParam")
    for i, bounds in enumerate(d["auxiliary"]["eta_bounds"]):
        lines.append("ravel_aux_" + str(i) + " param 0 1 [" + ",".join(_native_number(v) for v in bounds) + "]")
    return ("\n".join(lines) + "\n").encode()


def native_bridge_source(compiled):
    if compiled != response(compiled["document"]):
        raise ValueError("construction lowering changed")
    d = compiled["document"]
    lines = ["from HiggsAnalysis.CombinedLimit.PhysicsModel import PhysicsModel", "", "class RegionalModel(PhysicsModel):", "    def doParametersOfInterest(self):"]
    for p in d["parameters"]:
        literal = p["name"] + "[" + ",".join(_native_number(v) for v in [p["initial"], *p["bounds"]]) + "]"
        lines.append("        self.modelBuilder.doVar(" + repr(literal) + ")")
        lines.append("        self.modelBuilder.out.var(" + repr(p["name"]) + ").setConstant(" + repr(p["fixed"]) + ")")
        if p["role"] != "poi" and not p["fixed"]:
            lines.append("        self.modelBuilder.extraNuisances.append(self.modelBuilder.out.var(" + repr(p["name"]) + "))")
    for i, bounds in enumerate(d["auxiliary"]["eta_bounds"]):
        literal = "ravel_aux_" + str(i) + "[0," + ",".join(_native_number(v) for v in bounds) + "]"
        lines.append("        self.modelBuilder.doVar(" + repr(literal) + ")")
    lines.append("        self.modelBuilder.doSet('POI', " + repr(compiled["domain"]["name"]) + ")")
    for literal in compiled.get("shape_observables",[]):
        lines.append("        self.modelBuilder.doVar("+repr(literal)+")")
        lines.append("        self.modelBuilder.out.var("+repr(literal.split("[")[0])+").setConstant(True)")
    for expr in compiled.get("shape_factories",[]):
        lines.append("        self.modelBuilder.factory_(" + repr(expr) + ")")
    for declaration in compiled.get("shape_integrals",[]):
        lines.extend(continuous_dijet_shapes.native_bridge_lines(declaration))
    for expr in compiled["factories"]:
        lines.append("        self.modelBuilder.factory_(" + repr(expr) + ")")
    # Combine's param builder copies eta's finite parameter bounds to eta_In.
    # The supplied law instead has a full Gaussian auxiliary observation with a
    # bounded parameter domain. done() runs after doNuisances, before ModelConfig
    # and workspace persistence; it changes only these generated observations.
    lines.extend(["        self.modelBuilder.doModelBOnly = False", "", "    def done(self):"])
    if d["auxiliary"]["names"]:
        for i in range(len(d["auxiliary"]["names"])):
            name = "ravel_aux_" + str(i) + "_In"
            lines.extend(["        observation = self.modelBuilder.out.var(" + repr(name) + ")",
                          "        if not observation: raise ValueError('constructed Gaussian observation absent')",
                          "        observation.removeRange()",
                          "        observation.setConstant(True)"])
    else:
        lines.append("        pass")
    lines.extend(["", "    def getYieldScale(self, bin, process):", "        if process == 'ravel_dummy': return 0", "        if process != 'ravel_full': raise ValueError('undeclared constructed process')", "        return " + repr({v["bin"]: name for name, v in compiled["functions"].items()}) + "[bin]", "", "model = RegionalModel()", ""])
    return "\n".join(lines)


def native_witness(compiled, state):
    """Compare at the actual complete native coordinate state, not guessed zeros."""
    d = compiled["document"]
    if type(state) is not dict or set(state) != set(compiled["coordinates"]):
        raise ValueError("complete native construction state required")
    point = {}
    for name, row in state.items():
        _keys(row, {"value", "minimum", "maximum", "constant"}, "native coordinate")
        p = next((p for p in d["parameters"] if p["name"] == name), None)
        bounds = p["bounds"] if p else d["auxiliary"]["eta_bounds"][int(name.rsplit('_', 1)[1])]
        fixed = p["fixed"] if p else False
        if [row["minimum"], row["maximum"]] != [float(_q(v)) for v in bounds] or type(row["constant"]) is not bool or row["constant"] != fixed:
            raise ValueError("native construction bounds/fixed flags changed")
        # Native binary64 is the observed coordinate; retain its exact binary value.
        if type(row["value"]) not in (int, float) or not math.isfinite(row["value"]):
            raise ValueError("nonfinite native construction coordinate")
        point[name] = str(Fraction(row["value"]))
        if fixed and row["value"] != float(_q(p["initial"])):
            raise ValueError("native fixed parameter changed")
    # Exact rational source endpoints may round; use their native representation for
    # this native-only comparison. The original source law remains unmodified.
    observed = copy.deepcopy(d)
    for p in observed["parameters"]:
        p["bounds"] = [str(Fraction(float(_q(v)))) for v in p["bounds"]]
        p["initial"] = str(Fraction(float(_q(p["initial"]))))
    observed["auxiliary"]["eta_bounds"] = [[str(Fraction(float(_q(v)))) for v in b] for b in observed["auxiliary"]["eta_bounds"]]
    values = mean_jet(observed, point)
    if not values["strictly_positive_total"]:
        raise ValueError("native witness outside strict total-mean domain")
    return {name: values["means"][i] for i, name in enumerate(compiled["functions"])}


def write_native_bundle(document, output, *, runtime, fit, max_seconds):
    """Create a fresh ordinary native-likelihood input, without running it.

    Runtime and fit are the existing full native adapter contracts, supplied by
    the caller. This is not a readiness/approval claim; ordinary task_inputs must
    validate them and the pinned construction sources before planning/execution.
    """
    d = validate(document); response(d)
    if "expected_data" in d:
        from ravel.physics import regional_expected
        regional_expected.validate_fit(d,fit)
    elif fit.get("method") != "MultiDimFit" or fit.get("data") != "observed":
        raise ValueError("constructed signed/regional model requires observed profiling, not automatic asymptotics")
    out = Path(output)
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("construction output must be fresh, with nonsymlink ancestors")
    if any(not Path(row["path"]).is_absolute() for row in d["sources"]):
        raise ValueError("bundle requires absolute source pins, so relocation does not change their meaning")
    source_inputs(d, Path.cwd())
    out.mkdir(parents=True)
    raw = (json.dumps(d, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    (out / "construction.json").write_bytes(raw)
    card = datacard(d); (out / "model.txt").write_bytes(card)
    pin = lambda name: {"path": str((out / name).resolve()), "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest()}
    model = {"files": [{**pin("model.txt"), "staged_path": "model.txt"}], "card": "model.txt",
             "regions": [{"channel": b["id"], "role": b["role"]} for b in d["bins"]], "physics_model": None,
             "signal_replacement": None, "construction": pin("construction.json")}
    config = {"schema_version": 2 if "saved_fit" in fit else 1, "source": d["question"], "model": model,
              "runtime": copy.deepcopy(runtime), "fit": copy.deepcopy(fit), "max_seconds": max_seconds}
    if "expected_data" in d:
        config["expected_data"]=copy.deepcopy(d["expected_data"])
    (out / "native-input.json").write_text(json.dumps(config, sort_keys=True, indent=2, allow_nan=False) + "\n")
    source_inputs(d, Path.cwd())
    handoff = {"mode": "native-likelihood", "task": {"input": str((out / "native-input.json").resolve())}, "construction": pin("construction.json"),
               "source_law": KIND, "build_or_fit_executed": False, "native_parity_qualified": False,
               "remaining": ["ordinary source/runtime/fit admission", "native full-mean, auxiliary and domain qualification", "actual saved-fit/profile diagnostics", "interval/calibration/applicability if requested"]}
    (out / "handoff.json").write_text(json.dumps(handoff, sort_keys=True, indent=2) + "\n")
    return handoff
