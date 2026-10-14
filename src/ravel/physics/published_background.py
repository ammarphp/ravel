"""Published background/auxiliary block for a separately specified MC law.

This joins supplied source-coordinate signal expectations to the retained
background and auxiliary experiment. It does not infer response variations,
fit a model, or certify a generator's MC law. A pooled signal/background MC
constraint requires the explicit rebuild policy and exact background source.
"""
from copy import deepcopy
import hashlib
import json
import math


MC_TYPES = {"staterror", "shapesys"}
POLICIES = {"separable_signal_mc", "rebuild_background_mc_from_source"}


def _compact(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + " must be finite")
    return float(value)


def inspect_workspace(workspace, signal_samples):
    """Pure metadata census, with exact explicit signal identity per channel."""
    channels = workspace["channels"]
    if set(signal_samples) != {c["name"] for c in channels}:
        raise ValueError("signal sample mapping must cover every source channel")
    occurrences, background = {}, deepcopy(workspace)
    for channel, kept in zip(channels, background["channels"]):
        declared = signal_samples[channel["name"]]
        if not isinstance(declared, list) or not declared or len(set(declared)) != len(declared):
            raise ValueError("explicit nonempty unique signal sample list required")
        if not set(declared).issubset(s["name"] for s in channel["samples"]):
            raise ValueError("declared signal sample absent from source")
        kept["samples"] = [s for s in kept["samples"] if s["name"] not in declared]
        if not kept["samples"]:
            raise ValueError("each channel needs a source background sample")
        for sample in channel["samples"]:
            for modifier in sample["modifiers"]:
                occurrences.setdefault(modifier["name"], []).append({
                    "channel": channel["name"], "sample": sample["name"],
                    "type": modifier["type"], "signal": sample["name"] in declared})
    signal_mc = sorted(name for name, rows in occurrences.items()
                       if any(row["signal"] and row["type"] in MC_TYPES for row in rows))
    for name in signal_mc:
        if len({row["type"] for row in occurrences[name]}) != 1:
            raise ValueError("MC name is shared with a different modifier type")
    pooled = {name: occurrences[name] for name in signal_mc
              if any(not row["signal"] for row in occurrences[name])}
    return {"workspace_sha256": hashlib.sha256(_compact(workspace)).hexdigest(),
            "signal_mc_names": signal_mc, "pooled_signal_background_mc": pooled,
            "signal_exclusive_mc": [name for name in signal_mc if name not in pooled],
            "background_projection": background, "occurrences": occurrences}


def _auxiliary_layout(model):
    rows = []
    for name in model.config.auxdata_order:
        pset = model.config.param_set(name)
        part = model.config.par_map[name]["slice"]
        if pset.pdf_type not in ("normal", "poisson"):
            raise ValueError("unsupported source auxiliary distribution")
        sigma = getattr(pset, "sigmas", [1.] * pset.n_parameters)
        factors = getattr(pset, "factors", [1.] * pset.n_parameters)
        for offset in range(pset.n_parameters):
            rows.append({"name": name, "coordinate": model.config.par_names[part.start + offset],
                         "pdf": pset.pdf_type, "sigma": float(sigma[offset]),
                         "factor": float(factors[offset]), "observed": float(pset.auxdata[offset])})
    if len(rows) != model.config.nauxdata:
        raise ValueError("auxiliary layout does not cover source data")
    return rows


def _log_poisson(observed, mean):
    if mean < 0:
        raise ValueError("negative expected count")
    if mean == 0:
        return 0. if observed == 0 else -math.inf
    return observed * math.log(mean) - mean - math.lgamma(observed + 1)


class BackgroundAuxBlock:
    """Immutable serialized source plus compiled NumPy evaluator.

    In rebuild mode source MC constraints are recalculated using only the exact
    supplied background samples. This is a distinct statistical construction;
    it is deliberately not the original signal-patched auxiliary experiment.
    """
    def __init__(self, workspace, signal_samples, *, measurement, policy,
                 model_id, background_source=None):
        import pyhf
        from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS
        if pyhf.__version__ != "0.7.6" or pyhf.get_backend()[0].name != "numpy":
            raise ValueError("background block requires explicit pyhf 0.7.6 NumPy runtime")
        if policy not in POLICIES or not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("explicit new model identity and MC construction policy required")
        self._workspace_json = _compact(workspace)
        census = inspect_workspace(workspace, signal_samples)
        if census["pooled_signal_background_mc"] and policy == "separable_signal_mc":
            raise ValueError("pooled signal/background MC requires explicit background reconstruction")
        if policy == "rebuild_background_mc_from_source":
            if background_source is None or _compact(background_source) != _compact(census["background_projection"]):
                raise ValueError("exact published background source differs from signal-stripped workspace")
        elif background_source is not None:
            raise ValueError("background source only belongs to explicit rebuild policy")
        source = pyhf.Workspace(json.loads(self._workspace_json))
        self._model = source.model(measurement_name=measurement, modifier_settings=MODIFIER_SETTINGS)
        self._source_data = [float(x) for x in source.data(self._model)]
        self._inits = [float(x) for x in self._model.config.suggested_init()]
        self._bounds = self._model.config.suggested_bounds()
        self._names = list(self._model.config.par_names)
        self._poi = self._model.config.poi_name
        poi_rows = census["occurrences"].get(self._poi, [])
        if not poi_rows or any(not r["signal"] or r["type"] != "normfactor" for r in poi_rows):
            raise ValueError("source POI must be a signal-exclusive normfactor")
        for channel in workspace["channels"]:
            for sample in channel["samples"]:
                if sample["name"] in signal_samples[channel["name"]]:
                    poi_modifiers = [m for m in sample["modifiers"] if m["name"] == self._poi]
                    if len(poi_modifiers) != 1 or poi_modifiers[0]["type"] != "normfactor":
                        raise ValueError("every declared signal sample must carry the source POI normfactor")
        if self._model.config.param_set(self._poi).n_parameters != 1:
            raise ValueError("source signal strength must be scalar")
        original_aux = _auxiliary_layout(self._model)
        replaced = set(census["signal_mc_names"])
        new_aux, background_hash = [], None
        self._fixed = list(self._model.config.suggested_fixed())
        if policy == "rebuild_background_mc_from_source":
            bg = pyhf.Workspace(deepcopy(background_source))
            bg_model = bg.model(measurement_name=measurement, poi_name=None,
                               modifier_settings=MODIFIER_SETTINGS)
            background_hash = hashlib.sha256(_compact(background_source)).hexdigest()
            for name in census["pooled_signal_background_mc"]:
                original_support = {row["channel"] for row in census["occurrences"][name]}
                background_support = {row["channel"] for row in census["occurrences"][name] if not row["signal"]}
                if (original_support != background_support or
                        self._model.config.param_set(name).n_parameters != bg_model.config.param_set(name).n_parameters):
                    raise ValueError("pooled MC channel/bin support changed; textual coordinate names cannot establish correspondence")
            new_aux = [row for row in _auxiliary_layout(bg_model) if row["name"] in replaced]
            if any(row["coordinate"] not in self._names for row in new_aux):
                raise ValueError("background MC rebuild changed source coordinate correspondence")
            for bg_index, name in enumerate(bg_model.config.par_names):
                if name in {row["coordinate"] for row in new_aux}:
                    original_index = self._names.index(name)
                    self._fixed[original_index] = bg_model.config.suggested_fixed()[bg_index]
                    self._inits[original_index] = float(bg_model.config.suggested_init()[bg_index])
                    self._bounds[original_index] = bg_model.config.suggested_bounds()[bg_index]
        # Retain non-replaced source factors once, including signal-only response
        # nuisances. Background and signal share each remaining physical coordinate.
        self._aux = [r for r in original_aux if r["name"] not in replaced] + new_aux
        removed = set(census["signal_exclusive_mc"])
        excluded_indices = {self._model.config.poi_index}
        for name in removed:
            part = self._model.config.par_map[name]["slice"]
            excluded_indices.update(range(part.start, part.stop))
        self._active = [i for i in range(len(self._names)) if i not in excluded_indices]
        self.channels = list(self._model.config.channels)
        self.channel_slices = {k: [v.start, v.stop] for k, v in self._model.config.channel_slices.items()}
        self._contract = {"schema_version": 1, "model_id": model_id, "policy": policy,
            "source_workspace_sha256": census["workspace_sha256"], "background_source_sha256": background_hash,
            "measurement": measurement, "modifier_settings": deepcopy(MODIFIER_SETTINGS),
            "channel_order": deepcopy(self.channels), "channel_slices": deepcopy(self.channel_slices),
            "active_parameter_names": [self._names[i] for i in self._active],
            "active_parameter_domains": {self._names[i]: {"bounds": list(self._bounds[i]),
                "fixed": bool(self._fixed[i]), "initial": self._inits[i]} for i in self._active},
            "removed_signal_mc_parameters": census["signal_exclusive_mc"],
            "reconstructed_pooled_mc_names": sorted(census["pooled_signal_background_mc"]),
            "original_replaced_auxiliaries": [r for r in original_aux if r["name"] in replaced],
            "replacement_background_auxiliaries": new_aux, "retained_auxiliaries": self._aux,
            "scope": "Joined background/auxiliary evaluator; response and generator MC law supplied separately",
            "original_patched_auxiliary_equivalence": not replaced,
            "physics_validated": False}
        self.contract_sha256 = hashlib.sha256(_compact(self._contract)).hexdigest()

    def contract(self):
        return deepcopy(self._contract)

    def initial_point(self):
        return {self._names[i]: self._inits[i] for i in self._active}

    def _point(self, point):
        if not isinstance(point, dict) or set(point) != {self._names[i] for i in self._active}:
            raise ValueError("all retained source coordinates required exactly")
        vector = list(self._inits)
        vector[self._model.config.poi_index] = 0.
        for index in self._active:
            x = _number(point[self._names[index]], "source coordinate")
            if not self._bounds[index][0] <= x <= self._bounds[index][1]:
                raise ValueError("source coordinate outside retained domain")
            if self._fixed[index] and x != self._inits[index]:
                raise ValueError("source fixed coordinate changed")
            vector[index] = x
        return vector

    def background_means(self, point):
        values = self._model.expected_actualdata(self._point(point)).tolist()
        if any(not math.isfinite(v) or v < 0 for v in values):
            raise ValueError("invalid source background expectation")
        return values

    def auxiliary_logpdf(self, point, observations=None):
        self._point(point)
        observed = [r["observed"] for r in self._aux] if observations is None else observations
        if not isinstance(observed, list) or len(observed) != len(self._aux):
            raise ValueError("ordered retained auxiliary observations required")
        terms = []
        for row, value in zip(self._aux, observed):
            x = _number(value, "auxiliary observation")
            parameter = point[row["coordinate"]]
            if row["pdf"] == "normal":
                terms.append(-.5 * ((x - parameter) / row["sigma"]) ** 2
                             - math.log(row["sigma"] * math.sqrt(2 * math.pi)))
            else:
                if x < 0:
                    raise ValueError("Poisson auxiliary observation must be nonnegative")
                terms.append(_log_poisson(x, row["factor"] * parameter))
        return math.fsum(terms)

    def draw_auxiliary(self, point, rng):
        self._point(point)
        return [float(rng.normal(point[r["coordinate"]], r["sigma"])) if r["pdf"] == "normal"
                else int(rng.poisson(r["factor"] * point[r["coordinate"]])) for r in self._aux]

    def join(self, point, signal, *, mu, observations=None, auxiliary_observations=None):
        """Evaluate a source-coordinate-bound supplied signal plus background.

        The finite-MC block adds its own auxiliary log density to this result.
        ``signal`` must bind this exact construction and complete source point;
        that custody condition does not validate its response implementation.
        """
        mu = _number(mu, "signal strength")
        if mu < 0:
            raise ValueError("signal strength must be nonnegative")
        required = {"background_contract_sha256", "source_point", "means", "provenance"}
        if not isinstance(signal, dict) or set(signal) != required or signal["background_contract_sha256"] != self.contract_sha256:
            raise ValueError("signal must bind exact background construction")
        if signal["source_point"] != point or not isinstance(signal["provenance"], str) or not signal["provenance"].strip():
            raise ValueError("signal response must identify provenance and the same source point")
        means = signal["means"]
        if not isinstance(means, list) or len(means) != self._model.config.nmaindata:
            raise ValueError("complete signal vector required in declared channel/bin order")
        means = [_number(v, "signal expectation") for v in means]
        if any(v < 0 for v in means):
            raise ValueError("physical latent signal expectation must be nonnegative")
        b = self.background_means(point)
        total = [x + mu * y for x, y in zip(b, means)]
        if any(not math.isfinite(v) for v in total):
            raise ValueError("joined expectation overflow")
        n = self._source_data[:self._model.config.nmaindata] if observations is None else observations
        if not isinstance(n, list) or len(n) != len(total):
            raise ValueError("complete main observations required")
        n = [_number(v, "main observation") for v in n]
        if any(v < 0 for v in n):
            raise ValueError("main observations must be nonnegative")
        main = math.fsum(_log_poisson(x, y) for x, y in zip(n, total))
        aux = self.auxiliary_logpdf(point, auxiliary_observations)
        finite = math.isfinite(main) and math.isfinite(aux)
        return {"background_means": b, "signal_means": means, "main_means": total,
                "main_logpdf": main if math.isfinite(main) else None,
                "source_auxiliary_logpdf": aux if math.isfinite(aux) else None,
                "logpdf_before_new_mc_auxiliary": main + aux if finite else None,
                "finite": finite, "zero_probability": not finite,
                "physics_validated": False}
