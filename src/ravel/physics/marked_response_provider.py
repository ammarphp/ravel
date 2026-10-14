"""Absolute marked signal jets for the existing analytic joint likelihood.

No density, auxiliary, optimizer or calibration is created here. One complete
categorical population is shared across all anchors. Scientific admission of
that supplied population remains separate from these structural checks.
"""
from copy import deepcopy
from fractions import Fraction
from itertools import product
import hashlib
import json
import math
from pathlib import Path

from ravel.physics import marked_response as marks


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _read(path):
    path = Path(path)
    _require(not path.is_symlink() and path.is_file(), "regular response input required")
    _require(not any(p.is_symlink() for p in path.parents), "response symlink ancestor refused")
    with path.open("rb") as stream:
        raw = stream.read(8*1024**2+1)
    _require(len(raw) <= 8*1024**2, "response input exceeds 8 MiB")
    return raw


def smooth_mark_law(document):
    """Exact decimal-rational equality of both mark slopes at every knot.

Testing all other-axis anchors suffices because the remaining interpolation
is multilinear. Equality is required category by category, not only at one p.
No approximate kink smoothing or source-domain truncation is performed.
"""
    d = marks.prepare(document)
    F = lambda x: Fraction(str(x))
    table = {tuple(a["point"]): a["allocation"] for a in d["anchors"]}
    for j, axis in enumerate(d["axes"]):
        others = [a["knots"] if k != j else [None] for k, a in enumerate(d["axes"])]
        for point in product(*others):
            for left, middle, right in zip(axis["knots"], axis["knots"][1:], axis["knots"][2:]):
                rows = []
                for value in (left, middle, right):
                    p = list(point); p[j] = value; rows.append(table[tuple(p)])
                for k, weight in enumerate(d["category_weights"]):
                    for b in range(len(d["destination_ids"])):
                        lo = F(weight)*(F(rows[1][k][b])-F(rows[0][k][b]))/(F(middle)-F(left))
                        hi = F(weight)*(F(rows[2][k][b])-F(rows[1][k][b]))/(F(right)-F(middle))
                        _require(lo == hi, "nonsmooth category mark: smooth profiler cannot average knot slopes")
    return True


def bind_mark_law(document, configuration, source, mc_document, required_dependencies, source_bin_ids):
    """Pure contract arithmetic, invoked before source graph compilation.

Reference equality is checked for EVERY category mark, not just at empirical p.
Auxiliary order is retained verbatim; the provider contributes zero factors.
"""
    d = marks.prepare(document)
    keys = {"axis_to_source", "source_data_id", "group_ledger_source_id", "sampling_independence"}
    _require(type(configuration) is dict and set(configuration) == keys, "closed response provider configuration")
    mapping = configuration["axis_to_source"]
    names = source["active_parameter_names"]
    _require(type(mapping) is dict and set(mapping) == {a["name"] for a in d["axes"]}, "complete response-axis map")
    _require(all(type(v) is str and v in names for v in mapping.values()) and len(set(mapping.values())) == len(mapping), "injective retained source-coordinate map")
    _require(set(mapping.values()) == set(required_dependencies), "every source signal dependency must be explicitly replaced exactly once")
    _require(configuration["sampling_independence"] == "supplied_source_and_new_MC_auxiliaries_independent", "explicit source/MC independent experiment required")
    _require(type(configuration["source_data_id"]) is str and configuration["source_data_id"], "response source identity required")
    _require(type(configuration["group_ledger_source_id"]) is str and configuration["group_ledger_source_id"] and configuration["group_ledger_source_id"] != configuration["source_data_id"], "separate complete joint-mark group ledger required")
    design = mc_document["mc_design"]; classes = mc_document["classes"]
    _require(design["kind"] == "fixed_n_categories" and design["sampling_law"] == "iid_fixed_mark_categories", "marked provider requires exact fixed-N categorical sampling law")
    _require(design["fixed_marks"] is True and design["support_complete"] is True and design["independence"] == "iid_groups_within_one_fixed_N_stream", "complete IID fixed marks required")
    _require(d["category_ids"] == [c["id"] for c in classes], "complete ordered category population differs")
    _require(d["total_groups"] == design["total_groups"] and d["scale"] == design["kappa"], "MC count or normalization differs")
    _require(d["denominator_marks"] == [c["denominator_mark"] for c in classes], "complete denominator marks differ")
    bins = [b["id"] for b in mc_document["bins"]]
    _require(d["fitted_destinations"] == bins, "complete ordered fitted marks differ from MC bins")
    _require(len(source_bin_ids) == len(bins) and len(set(source_bin_ids)) == len(bins) and set(source_bin_ids) == set(bins), "source-bin permutation must be complete and injective")
    reference = tuple(d["reference_point"][a["name"]] for a in d["axes"])
    allocation = next(a["allocation"] for a in d["anchors"] if tuple(a["point"]) == reference)
    indices = [d["destination_ids"].index(b) for b in bins]
    for k, c in enumerate(classes):
        expected = [Fraction(str(d["category_weights"][k]))*Fraction(str(allocation[k][i])) for i in indices]
        _require(expected == [Fraction(str(v)) for v in c["contribution"]], "per-category reference marks differ; nominal agreement alone is insufficient")
    domains = source["active_parameter_domains"]
    for axis in d["axes"]:
        row = domains[mapping[axis["name"]]]
        extent = [row["initial"], row["initial"]] if row["fixed"] else row["bounds"]
        _require(axis["knots"][0] <= extent[0] <= extent[1] <= axis["knots"][-1], "response hull must cover the unchanged source domain")
    aux = source["retained_auxiliaries"]
    identities = [(r["name"], r["coordinate"]) for r in aux]
    _require(len(set(identities)) == len(identities), "duplicate retained source auxiliary identity")
    _require(all(r["coordinate"] in names for r in aux), "source auxiliary coordinate absent")
    smooth_mark_law(d)
    return {"schema": "complete-marked-response-provider-v1", "response_sha256": hashlib.sha256(_bytes(d)).hexdigest(),
            "source_contract_sha256": hashlib.sha256(_bytes(source)).hexdigest(),
            "MC_document_sha256": hashlib.sha256(_bytes(mc_document)).hexdigest(),
            "source_order": list(names), "MC_order": d["category_ids"], "source_bin_ids": list(source_bin_ids),
            "axis_to_source": deepcopy(mapping), "normalization": {"N": d["total_groups"], "scale": d["scale"], "denominator_marks": d["denominator_marks"]},
            "source_auxiliary_order": deepcopy(aux), "MC_auxiliary_factors": 1, "added_auxiliary_factors": 0,
            "sampling_independence": configuration["sampling_independence"],
            "domain": "unchanged source box, complete simplex, positive denominator, nonnegative reference and current fitted means",
            "smoothness": "exact category-wise C1 across all knots; no extrapolation",
            "law": "new_piecewise_multilinear_fixed_mark_law", "physics_validated": False}


def category_mark_records(document):
    """Canonical COMPLETE response signature, never nominal-only clustering."""
    d = marks.prepare(document)
    anchors = sorted(d["anchors"], key=lambda a: tuple(a["point"]))
    return [{"id": name, "weight": d["category_weights"][k], "denominator_mark": d["denominator_marks"][k],
             "anchors": [{"point": a["point"], "allocation": a["allocation"][k]} for a in anchors]}
            for k, name in enumerate(d["category_ids"])]


def verify_group_marks(document, mc_document, ledger):
    """Bind every observed group's full joint signature to the MC identities.

This proves internal source consistency, not that a generator or detector
actually produced the declared marks. Those source observations remain an
independent scientific prerequisite for physical use.
"""
    _require(type(ledger) is dict and set(ledger) == {"schema_version", "sampling_unit", "category_marks", "groups"}, "closed complete joint-mark ledger")
    _require(type(ledger["schema_version"]) is int and ledger["schema_version"] == 1 and ledger["sampling_unit"] == "same_complete_IID_generator_groups_at_all_anchors", "same-group sampling unit required")
    records = category_mark_records(document)
    _require(ledger["category_marks"] == records, "full category joint-anchor marks differ")
    signatures = {r["id"]: hashlib.sha256(_bytes(r)).hexdigest() for r in records}
    observed = {r["id"]: [] for r in mc_document["classes"]}
    _require(isinstance(ledger["groups"], list), "complete observed group-signature population required")
    for row in ledger["groups"]:
        _require(type(row) is dict and set(row) == {"id", "class_id", "category_mark_sha256"}, "closed observed group signature")
        _require(row["class_id"] in signatures and row["category_mark_sha256"] == signatures[row["class_id"]], "observed group has different joint-anchor signature")
        observed[row["class_id"]].append(row["id"])
    _require(all(observed[c["id"]] == c["observed_group_ids"] for c in mc_document["classes"]), "full response group identities/counts differ from MC ledger")
    return {"joint_mark_ledger_sha256": hashlib.sha256(_bytes(ledger)).hexdigest(), "category_signatures": signatures,
            "observed_group_count": len(ledger["groups"]), "source_mark_truth_independently_qualified": False}


def mark_jet(document, point, latent, source_names, axis_to_source, source_bin_ids):
    """Absolute means and complete Jacobians, including zero nominal bins.

Negative fitted marks remain available to the constraint evaluator; density
admission separately rejects negative physical aggregate expectations.
"""
    d = marks.prepare(document)
    smooth_mark_law(d)
    p, denominator = marks._population(d, latent)
    source_point = {axis: point[name] for axis, name in axis_to_source.items()}
    cells = marks._intervals(d, source_point); cell = [c[0] for c in cells]
    matrix = marks._marks(d, source_point, cell)
    rows = [d["destination_ids"].index(b) for b in source_bin_ids]
    numerators = [math.fsum(a*b for a, b in zip(matrix[i], p)) for i in rows]
    values = [d["scale"]*(x/denominator) for x in numerators]
    latent_jac = [[d["scale"]*(matrix[i][k]/denominator - (numerators[j]/denominator)*(d["denominator_marks"][k]/denominator))
                   for k in range(len(p))] for j, i in enumerate(rows)]
    source_jac = [[0.]*len(source_names) for _ in rows]
    for j, axis in enumerate(d["axes"]):
        dm = marks._marks(d, source_point, cell, derivative_axis=j)
        k = source_names.index(axis_to_source[axis["name"]])
        for b, i in enumerate(rows):
            source_jac[b][k] = d["scale"]*(math.fsum(a*q for a, q in zip(dm[i], p))/denominator)
    all_numbers = values + [v for row in latent_jac+source_jac for v in row]
    _require(all(math.isfinite(v) for v in all_numbers), "marked response derivative overflow")
    return {"signal": values, "source_jacobian": source_jac, "latent_jacobian": latent_jac,
            "expected_denominator": denominator, "source_order": list(source_names), "MC_order": d["category_ids"],
            "domain_residuals": values+[denominator], "strict_positive_residual_indices": [len(values)],
            "added_auxiliary_factors": 0}


class MarkedResponseProvider:
    """Byte-bound complete-law provider; bind once to the actual joined blocks."""
    def __init__(self, *, path, sha256, configuration):
        self._path = Path(path).absolute(); self._raw = _read(self._path)
        _require(hashlib.sha256(self._raw).hexdigest() == sha256, "response source hash differs")
        self._document = marks.prepare(json.loads(self._raw))
        self._configuration = json.loads(_bytes(configuration)); self._binding = None

    def assert_custody(self):
        _require(_read(self._path) == self._raw, "response source changed")

    def bind(self, source, mc, required_dependencies, source_bin_ids):
        _require(self._binding is None, "response provider already bound; create a distinct instance")
        self.assert_custody(); mc.assert_custody()
        document = mc.document()
        pins = [p for p in document["sources"] if p["id"] == self._configuration["source_data_id"]]
        _require(len(pins) == 1 and pins[0]["sha256"] == hashlib.sha256(self._raw).hexdigest(), "response must be part of the exact MC source capture")
        _require(any(raw == self._raw for raw in mc._captured.values()), "response bytes absent from complete MC source capture")
        group_pins = [p for p in document["sources"] if p["id"] == self._configuration["group_ledger_source_id"]]
        _require(len(group_pins) == 1, "complete joint-mark ledger source absent")
        group_bytes = [raw for raw in mc._captured.values() if hashlib.sha256(raw).hexdigest() == group_pins[0]["sha256"]]
        _require(bool(group_bytes), "complete joint-mark ledger bytes absent")
        group_binding = verify_group_marks(self._document, document, json.loads(group_bytes[0]))
        self._binding = bind_mark_law(self._document, self._configuration, source, document, required_dependencies, source_bin_ids)
        self._binding["complete_group_marks"] = group_binding
        self._binding["source_pin"] = {"path": str(self._path), "sha256": hashlib.sha256(self._raw).hexdigest()}
        self.assert_custody()
        return self.contract()

    def contract(self):
        _require(self._binding is not None, "provider has not been joined to source/MC law")
        return deepcopy(self._binding)

    def jet(self, source_point, latent):
        self.assert_custody(); b = self.contract()
        result = mark_jet(self._document, source_point, latent, b["source_order"], b["axis_to_source"], b["source_bin_ids"])
        self.assert_custody()
        return result

    def shared_template_covariance(self, source_points, latent):
        """Complete same-MC-population propagation, with its exact/delta label.

        This is a template-estimator diagnostic. It never appends an auxiliary
        factor or treats fitted probabilities as independently measured bins.
        """
        self.assert_custody(); binding = self.contract()
        mapping = binding["axis_to_source"]
        points = [{axis: point[name] for axis, name in mapping.items()} for point in source_points]
        result = marks.joint_covariance(self._document, latent, points)
        self.assert_custody()
        return result

    def supported_categories(self):
        d = self._document; fitted = [d["destination_ids"].index(b) for b in d["fitted_destinations"]]
        return [k for k in range(len(d["category_ids"])) if d["category_weights"][k] != 0 and
                any(a["allocation"][k][b] != 0 for a in d["anchors"] for b in fitted)]


def assemble_main_jet(background, background_jacobian, signal_jet, mu):
    """Pure chain rule used by the joined density, no nominal division."""
    _require(type(mu) in (int, float) and math.isfinite(mu) and mu >= 0, "nonnegative finite strength")
    signal = signal_jet["signal"]; js = signal_jet["source_jacobian"]; jp = signal_jet["latent_jacobian"]
    _require(len(background) == len(background_jacobian) == len(signal) == len(js) == len(jp), "complete main-bin derivative population")
    source_count = len(signal_jet["source_order"]); latent_count = len(signal_jet["MC_order"])
    _require(all(len(b) == len(s) == source_count and len(p) == latent_count for b, s, p in zip(background_jacobian, js, jp)), "complete derivative columns")
    _require(all(v >= 0 for v in background+signal), "negative aggregate background or transported signal")
    values = [b+mu*s for b, s in zip(background, signal)]
    jac = [[s]+[a+mu*b for a, b in zip(jb, jsource)]+[mu*a for a in jlatent]
           for s, jb, jsource, jlatent in zip(signal, background_jacobian, js, jp)]
    _require(all(math.isfinite(v) for v in values+[v for row in jac for v in row]), "main derivative overflow")
    return values, jac
