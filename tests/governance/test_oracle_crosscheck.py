"""Cross-checks of the WP12 oracles against the RAVEL kernel and stock pyhf (task-bank plan step 3).

The oracles (benchmarks/governance/oracle/counting.py and lhe_census.py) are standard-library code
that never imports pyhf or ravel. The tests here do, on purpose: they measure agreement between an
oracle and the code it will score. Marks:

- ``kernel_crosscheck``: imports the RAVEL kernel (src/ravel) or stock pyhf; skips when pyhf 0.7.6,
  scipy or the kernel is unavailable. Stock pyhf results are implementation evidence only: pyhf is
  the library the kernel wraps, so agreement with it is not independent validation.
- ``diagnostic``: records a measurement (toy MC calibration, level sensitivity) that is not a
  correctness criterion; its assertions are loose bands around the recorded values.
- Unmarked tests compare the oracle with kernel results already recorded in the repository.

Each test that measures a number prints one line ``CROSSCHECK <name> <json>`` with it (run pytest
with ``-s``). docs/development/evaluation-study/taskbank-oracle-appendix.md tabulates them.

Inputs and provenance:
- 2jl: n = 263, b = 283 +- 24 events transcribed from ATLAS arXiv:1605.03814, SR 2jl, in a single-bin
  gamma/Poisson approximation (derived_from_published; record benchmarks/scoped/atlas-2jl-counting.json).
  The POI cap 10 is a synthetic perturbation; the 2026-09-09 unresolved-bound control used it too.
- hv (n = 73, b = 58.0 +- 7.0) and the likelihood_freshness prior/V1 models are SYNTHETIC.
- The Drell-Yan LHE files are RAVEL-generated development samples; the content-truncated fixture is
  derived from one of them (fixtures/lhe/fixtures.json pins all three by sha256).
Nothing here is an agent result or a physics measurement.
"""
import contextlib
import gzip
import hashlib
import io
import json
import math
import os
import platform
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from governance.oracle import counting, lhe_census

ROOT = Path(__file__).resolve().parents[2]
SCOPED = ROOT / "evidence" / "audits" / "2026-09-09-scoped-workflows"
LHE_FIXTURES = ROOT / "tests" / "governance" / "fixtures" / "lhe"
PINNED = json.loads((LHE_FIXTURES / "fixtures.json").read_text())
TRUNCATED = ROOT / "benchmarks" / "governance" / "tasks" / "data" / "dy-1730-content-truncated.lhe.gz"
SELECTION = {"observable": "pair_invariant_mass", "unit": "GeV", "pdg_ids": [-11, 11], "status": 1,
             "multiplicity": "exactly_one_each", "window": [81, 101], "edges": "exclusive"}
DY_CONTROLS = {"dy-1729": "drell-yan", "dy-1730": "drell-yan-replica"}

# Counting models as the kernel's scoped route receives them (spec "counting" blocks).
MODELS = {
    "2jl-cap10": ({"observed": 263, "background": 283, "background_uncertainty": 24, "signal": 1}, 10),
    "2jl-cap256": ({"observed": 263, "background": 283, "background_uncertainty": 24, "signal": 1}, 256),
    "hv": ({"observed": 73, "background": 58.0, "background_uncertainty": 7.0, "signal": 1}, 256),
}
PUBLIC_2JL, SYNTHETIC_HV = (263, 283.0, 24.0), (73, 58.0, 7.0)
TOY_MODELS = {"lf-prior": (42, 38.0, 5.0), "lf-v1": (42, 44.0, 5.0), "2jl": PUBLIC_2JL, "hv": SYNTHETIC_HV}

# Bounds. Measured values (2026-09-26, macOS arm64, CPython 3.12.13, pyhf 0.7.6, numpy 1.26.4,
# scipy 1.14.1) are printed by each test and tabulated in the appendix.
# CLS_ATOL: absolute CLs agreement at one mu. The kernel and stock pyhf fit with an objective
# tolerance of 1e-9, which leaves their CLs uncertain at about 1e-8 (measured worst 2.0e-8 over
# every kernel scan point); 1e-7 keeps 5x headroom and is far below any scoring tolerance.
CLS_ATOL = 1e-7
# KERNEL_ROOT_RTOL: relative oracle-kernel limit agreement for hv and 2jl with cap 256. The kernel's
# brentq(xtol=1e-10, rtol=root_rtol=1e-4) guarantees |x - x*| < 1e-10 + 1e-4 |x| only against the
# root x* of the kernel's OWN CLs function, and that root moves from the oracle's by up to
# CLS_ATOL / (|dCLs/dmu| mu) relative. 1.5e-4 is root_rtol plus an allowance for both terms; the
# resolved-limit test checks that the allowance covers them at every root (it needs < 1e-6). The
# kernel's full contract, root_rtol plus root_cls_atol, allows up to ~0.3 %, so a kernel change inside
# that contract can still trip this bound: review such a change rather than widen the bound.
# test_oracle_counting keeps KERNEL_RTOL = 1e-3 for its fixtures.
KERNEL_BRENT_RTOL, KERNEL_BRENT_XTOL = 1e-4, 1e-10
KERNEL_ROOT_RTOL = 1.5e-4
# STOCK_PYHF_RTOL: as test_oracle_counting.STOCK_PYHF_RTOL, for scipy_optimizer(tolerance=1e-9); with
# tolerance 1e-12 the residual shrinks below STOCK_PYHF_TIGHT_RTOL, which shows it is the optimizer's.
STOCK_PYHF_RTOL = 1e-6
STOCK_PYHF_TIGHT_RTOL = 1e-7
MASS_RTOL = 1e-9   # the design's per-event mass agreement requirement


def record(name, payload):
    print(f"CROSSCHECK {name} {json.dumps(payload, sort_keys=True)}")


def cls_list(result):
    return [result["observed"], *result["expected"]]


def relative(a, b):
    return abs(a - b) / abs(b)


def kernel_mapped_status(oracle_status):
    return {"observed": counting.KERNEL_LIMIT_STATUS[oracle_status["observed"]],
            "expected": [counting.KERNEL_LIMIT_STATUS[s] for s in oracle_status["expected"]]}


def cls_slope(model, mu, index, poi_cap=256.0):
    """d CLs_index / d mu from the oracle by a central difference (a test-side derivative)."""
    h = 1e-5 * mu
    up = cls_list(counting.cls_at(*model, mu + h, poi_cap=poi_cap))[index]
    down = cls_list(counting.cls_at(*model, mu - h, poi_cap=poi_cap))[index]
    return (up - down) / (2 * h)


# --------------------------------------------------------------------------- kernel access

@pytest.fixture(scope="module")
def pyhf_module():
    pyhf = pytest.importorskip("pyhf", reason="pyhf is not installed; kernel cross-checks cannot run")
    pytest.importorskip("scipy", reason="scipy is not installed; the kernel needs brentq")
    if pyhf.__version__ != "0.7.6":
        pytest.skip(f"oracle definitions are pinned to pyhf 0.7.6, found {pyhf.__version__}")
    saved = pyhf.get_backend()
    yield pyhf
    pyhf.set_backend(*saved)


@pytest.fixture(scope="module")
def kernel(pyhf_module):
    try:
        from ravel.physics import pyhf_exclude, scoped
    except ImportError as exc:
        pytest.skip(f"ravel kernel unavailable: {exc}")
    return {"pyhf": pyhf_module, "compute": pyhf_exclude.compute, "robust_optimizer": pyhf_exclude.robust_optimizer,
            "MODIFIER_SETTINGS": pyhf_exclude.MODIFIER_SETTINGS, "prepare_workspace": scoped.prepare_workspace}


def kernel_workspace(kernel, label):
    """The workspace the kernel's scoped counting route builds (ravel.physics.scoped.prepare_workspace)."""
    counting_spec, cap = MODELS[label]
    return kernel["prepare_workspace"]({"likelihood": {"counting": counting_spec, "poi_cap": cap}}, ROOT)


def run_kernel(kernel, workspace, cap, modifier_settings=None):
    """pyhf_exclude.compute exactly as the scoped likelihood worker calls it."""
    pyhf = kernel["pyhf"]
    ws = pyhf.Workspace(workspace)
    model = ws.model(modifier_settings=modifier_settings) if modifier_settings else ws.model()
    data = ws.data(model)
    pyhf.set_backend("numpy", kernel["robust_optimizer"](tolerance=1e-9), precision="64b")
    with contextlib.redirect_stderr(io.StringIO()):
        return kernel["compute"](model, data, poi_cap=float(cap), diagnostic_record={})


@pytest.fixture(scope="module")
def kernel_runs(kernel):
    runs = {}
    for label, (_, cap) in MODELS.items():
        workspace = kernel_workspace(kernel, label)
        runs[label] = run_kernel(kernel, workspace, cap)
        if label != "2jl-cap256":
            runs[label + "+modifier-settings"] = run_kernel(kernel, workspace, cap, kernel["MODIFIER_SETTINGS"])
    return runs


def oracle_model(kernel, label):
    parsed = counting.parse_counting_workspace(kernel_workspace(kernel, label))
    return (parsed["n_obs"], parsed["background"], parsed["background_uncertainty"]), parsed["poi_cap"]


def scan_agreement(model, cap, result):
    """Worst |oracle CLs - kernel CLs| over every point of the kernel's own CLs scan."""
    worst = 0.0
    for mu, observed, expected in zip(result["scan_mu"], result["scan_cls_obs"], result["scan_cls_exp"]):
        ours = cls_list(counting.cls_at(*model, mu, poi_cap=cap))
        worst = max(worst, max(abs(a - b) for a, b in zip(ours, [observed, *expected])))
    return worst


# --------------------------------------------------------------------------- counting: RAVEL kernel

@pytest.mark.kernel_crosscheck
def test_kernel_route_builds_the_oracle_model(kernel):
    assert oracle_model(kernel, "2jl-cap10") == (PUBLIC_2JL, 10)
    assert oracle_model(kernel, "2jl-cap256") == (PUBLIC_2JL, 256)
    assert oracle_model(kernel, "hv") == (SYNTHETIC_HV, 256)


@pytest.mark.kernel_crosscheck
def test_kernel_2jl_cap_10_statuses_and_cls_at_the_cap(kernel, kernel_runs):
    model, cap = oracle_model(kernel, "2jl-cap10")
    ours = counting.limits(*model, poi_cap=cap)
    theirs = kernel_runs["2jl-cap10"]
    # statuses: the oracle's above_cap is the kernel's above_scan on all six curves
    assert ours["limit_status"] == {"observed": "above_cap", "expected": ["above_cap"] * 5}
    assert theirs["limit_status"] == kernel_mapped_status(ours["limit_status"])
    # the kernel keeps the cap as a numeric bound, flagged; the oracle's value is null
    assert theirs["obs_limit"] == 10.0 and theirs["exp_limits"] == [10.0] * 5
    assert ours["obs_limit_events"] is None and ours["exp_limits_events"] == [None] * 5
    assert theirs["at_poi_cap"] and theirs["median_at_cap"] and not theirs["at_mu_floor"]
    # CLs at the cap: the last kernel scan point is mu = 10
    assert theirs["scan_mu"][-1] == 10.0 == max(theirs["scan_mu"])
    kernel_at_cap = [theirs["scan_cls_obs"][-1], *theirs["scan_cls_exp"][-1]]
    oracle_at_cap = cls_list(counting.cls_at(*model, 10.0, poi_cap=cap))
    assert oracle_at_cap == cls_list(ours["cls_at_cap"])
    differences = [abs(a - b) for a, b in zip(oracle_at_cap, kernel_at_cap)]
    assert max(differences) <= CLS_ATOL, differences
    assert all(v > 0.05 for v in kernel_at_cap)
    worst = scan_agreement(model, cap, theirs)
    assert worst <= CLS_ATOL
    record("counting.kernel.2jl-cap10", {
        "oracle_status": ours["limit_status"], "kernel_status": theirs["limit_status"],
        "kernel_bounds": [theirs["obs_limit"], *theirs["exp_limits"]],
        "oracle_cls_at_10": oracle_at_cap, "kernel_cls_at_10": kernel_at_cap, "abs_differences": differences,
        "scan_points": len(theirs["scan_mu"]), "scan_worst_abs_difference": worst, "n_fits": theirs["n_fits"]})


@pytest.mark.kernel_crosscheck
@pytest.mark.parametrize("control, label", [("unresolved-bound", "2jl-cap10"), ("counting", "2jl-cap256")])
def test_kernel_reproduces_the_recorded_control(kernel_runs, control, label):
    # The 2026-09-09 scoped-workflow records are the kernel figures the design quotes; a fresh run of
    # the same kernel must reproduce them. Brent evaluations join the scan grid, so compare CLs at the
    # common points and the limits within the kernel's root tolerance.
    recorded = json.loads((SCOPED / control / "result.json").read_text())
    fresh = kernel_runs[label]
    assert fresh["limit_status"] == recorded["limit_status"]
    limits = [relative(a, b) for a, b in zip([fresh["obs_limit"], *fresh["exp_limits"]],
                                             [recorded["obs_limit"], *recorded["exp_limits"]])]
    assert max(limits) <= KERNEL_ROOT_RTOL
    fresh_points = {mu: [o, *e] for mu, o, e in zip(fresh["scan_mu"], fresh["scan_cls_obs"], fresh["scan_cls_exp"])}
    recorded_points = {mu: [o, *e] for mu, o, e in zip(recorded["scan_mu"], recorded["scan_cls_obs"],
                                                       recorded["scan_cls_exp"])}
    common = sorted(set(fresh_points) & set(recorded_points))
    assert len(common) >= 11                                        # at least the n_curve display grid
    worst = max(max(abs(a - b) for a, b in zip(fresh_points[mu], recorded_points[mu])) for mu in common)
    assert worst <= CLS_ATOL
    record(f"counting.kernel.{label}.vs-recorded-{control}", {
        "identical_scan_grid": fresh["scan_mu"] == recorded["scan_mu"], "common_points": len(common),
        "worst_abs_cls_difference": worst, "worst_relative_limit_difference": max(limits)})


@pytest.mark.kernel_crosscheck
@pytest.mark.parametrize("label", ["hv", "2jl-cap256"])
def test_kernel_resolved_limits_and_scan(kernel, kernel_runs, label):
    model, cap = oracle_model(kernel, label)
    ours = counting.limits(*model, poi_cap=cap)
    theirs = kernel_runs[label]
    assert ours["limit_status"] == theirs["limit_status"] == {"observed": "resolved", "expected": ["resolved"] * 5}
    oracle_values = [ours["obs_limit_events"], *ours["exp_limits_events"]]
    kernel_values = [theirs["obs_limit"], *theirs["exp_limits"]]
    differences = [relative(a, b) for a, b in zip(oracle_values, kernel_values)]
    assert max(differences) <= KERNEL_ROOT_RTOL, differences
    # the bound's allowance over root_rtol covers brentq's xtol and the root shift that a CLs
    # disagreement of CLS_ATOL implies (both far below it at these roots)
    shifts = [KERNEL_BRENT_XTOL / root + CLS_ATOL / (abs(cls_slope(model, root, i, cap)) * root)
              for i, root in enumerate(oracle_values)]
    assert KERNEL_BRENT_RTOL + max(shifts) < KERNEL_ROOT_RTOL, shifts
    worst = scan_agreement(model, cap, theirs)
    assert worst <= CLS_ATOL
    record(f"counting.kernel.{label}", {
        "oracle": oracle_values, "kernel": kernel_values, "relative_differences": differences,
        "structural_allowance_needed": max(shifts),
        "kernel_root_cls_max_error": theirs["inference"]["root_cls_max_error"],
        "scan_points": len(theirs["scan_mu"]), "scan_worst_abs_difference": worst, "n_fits": theirs["n_fits"],
        "band_degenerate": theirs["band_degenerate"]})


@pytest.mark.kernel_crosscheck
@pytest.mark.parametrize("label", ["2jl-cap10", "hv"])
def test_kernel_modifier_settings_leave_counting_results_unchanged(kernel_runs, label):
    # The generalized fit stage (design section 3.3) will pass MODIFIER_SETTINGS explicitly; they set
    # normsys/histosys interpolation codes, which a normfactor + shapesys model does not use.
    plain, explicit = kernel_runs[label], kernel_runs[label + "+modifier-settings"]
    for key in ("obs_limit", "exp_limits", "limit_status", "scan_mu", "scan_cls_obs", "scan_cls_exp"):
        assert plain[key] == explicit[key], key
    record(f"counting.kernel.{label}.modifier-settings", {"identical": True})


# --------------------------------------------------------------------------- counting: recorded kernel evidence

def test_recorded_kernel_controls_agree_with_the_oracle():
    """The 2026-09-09 scoped-workflow kernel records (no kernel import): the cap-10 and cap-256 2jl runs."""
    out = {}
    for control in ("unresolved-bound", "counting"):
        spec = json.loads((SCOPED / control / "spec.json").read_text())["likelihood"]
        c = spec["counting"]
        model, cap = (c["observed"], c["background"], c["background_uncertainty"]), spec["poi_cap"]
        assert c["signal"] == 1 and model == (263, 283, 24)
        recorded = json.loads((SCOPED / control / "result.json").read_text())
        ours = counting.limits(*model, poi_cap=cap)
        assert recorded["limit_status"] == kernel_mapped_status(ours["limit_status"])
        worst = scan_agreement(model, cap, recorded)
        assert worst <= CLS_ATOL
        out[control] = {"poi_cap": cap, "scan_points": len(recorded["scan_mu"]), "scan_worst_abs_difference": worst}
        if control == "counting":
            differences = [relative(a, b) for a, b in zip([ours["obs_limit_events"], *ours["exp_limits_events"]],
                                                         [recorded["obs_limit"], *recorded["exp_limits"]])]
            assert max(differences) <= KERNEL_ROOT_RTOL
            out[control]["relative_differences"] = differences
        else:
            assert ours["obs_limit_events"] is None and recorded["obs_limit"] == cap
            out[control]["recorded_cls_at_10"] = [recorded["scan_cls_obs"][-1], *recorded["scan_cls_exp"][-1]]
    record("counting.recorded-kernel", out)


# --------------------------------------------------------------------------- counting: stock pyhf (implementation evidence)

def stock_cls(pyhf, model, cap, mu):
    from governance.tasks.development.likelihood_freshness.family import counting_workspace
    ws = pyhf.Workspace(counting_workspace(*model, poi_cap=cap))
    pdf = ws.model()
    observed, expected = pyhf.infer.hypotest(mu, ws.data(pdf), pdf, test_stat="qtilde", return_expected_set=True)
    return [float(observed), *map(float, expected)]


@pytest.mark.kernel_crosscheck
@pytest.mark.parametrize("label, model", [("2jl", PUBLIC_2JL), ("hv", SYNTHETIC_HV)])
def test_stock_pyhf_hypotest_at_the_oracle_roots(pyhf_module, label, model):
    pyhf = pyhf_module
    ours = counting.limits(*model)
    roots = [ours["obs_limit_events"], *ours["exp_limits_events"]]
    slopes = [cls_slope(model, root, i) for i, root in enumerate(roots)]
    out = {"roots": roots}
    for tolerance, bound in ((1e-9, STOCK_PYHF_RTOL), (1e-12, STOCK_PYHF_TIGHT_RTOL)):
        pyhf.set_backend("numpy", pyhf.optimize.scipy_optimizer(tolerance=tolerance), precision="64b")
        residuals = [stock_cls(pyhf, model, 256.0, root)[i] - 0.05 for i, root in enumerate(roots)]
        # the root offset these residuals imply: |CLs(root) - level| / (|dCLs/dmu| * root)
        implied = [abs(r) / (abs(s) * root) for r, s, root in zip(residuals, slopes, roots)]
        assert max(implied) <= bound, implied
        out[f"tolerance_{tolerance:g}"] = {"cls_minus_level": residuals, "implied_relative_root_offset": implied}
    record(f"counting.stock-pyhf.roots.{label}", out)


@pytest.mark.kernel_crosscheck
def test_stock_pyhf_hypotest_at_mu_10(pyhf_module):
    pyhf = pyhf_module
    pyhf.set_backend("numpy", pyhf.optimize.scipy_optimizer(tolerance=1e-9), precision="64b")
    capped = stock_cls(pyhf, PUBLIC_2JL, 10.0, 10.0)
    uncapped = stock_cls(pyhf, PUBLIC_2JL, 256.0, 10.0)
    ours = cls_list(counting.cls_at(*PUBLIC_2JL, 10.0, poi_cap=10.0))
    assert ours == cls_list(counting.cls_at(*PUBLIC_2JL, 10.0))     # the cap does not enter CLs(10)
    differences = [abs(a - b) for a, b in zip(ours, capped)]
    assert max(differences) <= CLS_ATOL, differences
    assert max(abs(a - b) for a, b in zip(capped, uncapped)) <= 1e-12
    record("counting.stock-pyhf.mu10.2jl", {"oracle": ours, "stock_cap10": capped, "stock_cap256": uncapped,
                                            "abs_differences": differences})


# --------------------------------------------------------------------------- LHE: kernel readers

@pytest.fixture(scope="module")
def lhe_readers():
    try:
        from ravel.physics.native_normalization import read_lhe
        from ravel.physics.scoped import audit_lhe
    except ImportError as exc:
        pytest.skip(f"ravel kernel unavailable: {exc}")
    return {"audit_lhe": audit_lhe, "read_lhe": read_lhe}


def dy_file(label):
    entry = PINNED["referenced"][label]
    path = ROOT / entry["path"]
    assert path.parent.name == DY_CONTROLS[label]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    return path, json.loads((path.parent / "spec.json").read_text())["generation"]


@pytest.mark.kernel_crosscheck
@pytest.mark.parametrize("label", sorted(DY_CONTROLS))
def test_kernel_lhe_readers_agree_with_the_census(lhe_readers, label):
    path, plan = dy_file(label)
    audit = lhe_readers["audit_lhe"](path, plan)       # the redacted public file against its manifest plan
    normalization = lhe_readers["read_lhe"](path)
    census = lhe_census.census(path.read_bytes(), selection=SELECTION, expected_sha256=PINNED["referenced"][label]["sha256"])
    assert audit["passed"] is True and audit["sampling"] == {"events": 100, "seed": plan["seed"]}
    # the task-bank manifest.json carries the generation block without "runtime" (design section 2 P4/P5):
    # audit_lhe does not read it, so the census stage can audit against that manifest unchanged
    without_runtime = lhe_readers["audit_lhe"](path, {k: v for k, v in plan.items() if k != "runtime"})
    assert "runtime" in plan and without_runtime == audit
    assert census["physics_status"] == "computed"
    # event count
    assert audit["events"] == normalization["n_events"] == census["complete_events"] == census["header_nevents"] == 100
    # cross section (XSECUP, pb) and its integration error
    assert audit["cross_section_pb"] == normalization["cross_section_pb"] == census["cross_section_pb"]
    assert relative(audit["integration_error_pb"], census["integration_error_pb"]) <= 1e-15
    # weights
    assert normalization["negative_weights"] == 0
    weight_differences = [relative(normalization["sumw"], census["sum_weights"]),
                          relative(normalization["sumw2"], census["sum_weights_sq"])]
    assert max(weight_differences) <= 1e-12
    # per-event masses: the kernel's masses_gev is the mass of ALL status-1 particles; the oracle's is the
    # selected pair's. They coincide only because audit_lhe requires each event's final state to equal the
    # plan's final_state_pdg, which here equals the selection's pdg_ids. The step-4 census stage must enforce
    # that equality (or compute the pair mass from the selected particles) before it applies a selection
    # to the kernel's masses.
    assert sorted(plan["observable"]["final_state_pdg"]) == sorted(SELECTION["pdg_ids"])
    ours = lhe_census.pair_masses(path.read_bytes(), SELECTION)
    theirs = audit["masses_gev"]
    assert len(ours) == len(theirs) == 100 and None not in ours
    mass_differences = [relative(a, b) for a, b in zip(ours, theirs)]
    assert max(mass_differences) <= MASS_RTOL
    # the selection applied to the kernel's masses (as the census stage will) gives the oracle's count
    kernel_selected = sum(81 < m < 101 for m in theirs)
    assert kernel_selected == census["selected_events"]
    edge = min(min(abs(m - 81), abs(m - 101)) for m in theirs)
    assert abs(edge - census["min_edge_distance_gev"]) <= 1e-9
    record(f"lhe.kernel.{label}", {
        "events": audit["events"], "cross_section_pb": audit["cross_section_pb"],
        "integration_error_pb": audit["integration_error_pb"], "oracle_cross_section_exact": census["exact"]["cross_section_pb"],
        "sumw_relative_difference": weight_differences[0], "sumw2_relative_difference": weight_differences[1],
        "max_mass_relative_difference": max(mass_differences), "selected_kernel_masses": kernel_selected,
        "selected_oracle": census["selected_events"], "min_edge_distance_gev": edge,
        "edge_over_worst_mass_error": edge / max(max(abs(a - b) for a, b in zip(ours, theirs)), 1e-300)})


def kernel_outcome(call):
    try:
        call()
    except Exception as exc:    # the exact exception is the evidence
        return exc
    return None


@pytest.mark.kernel_crosscheck
def test_kernel_lhe_readers_on_the_content_truncated_fixture(lhe_readers):
    _, plan = dy_file("dy-1730")
    audit = kernel_outcome(lambda: lhe_readers["audit_lhe"](TRUNCATED, plan))
    normalization = kernel_outcome(lambda: lhe_readers["read_lhe"](TRUNCATED))
    content = gzip.decompress(TRUNCATED.read_bytes())
    lines = content.split(b"\n")
    # audit_lhe (ElementTree iterparse over the text stream) reaches end of input inside event 42
    assert type(audit) is ET.ParseError
    assert str(audit) == "no element found: line 738, column 32"
    assert audit.position == (len(lines), len(lines[-1])) == (738, 32)     # the end of the content
    assert audit.code == 3                                                    # expat XML_ERROR_NO_ELEMENTS
    # read_lhe (line reader) sees an open event block and no closing tag
    assert type(normalization) is ValueError and str(normalization) == "truncated LHE document"
    # the oracle reads the same bytes as 41 complete events and withholds physics
    census = lhe_census.census(TRUNCATED.read_bytes(), selection=SELECTION,
                               expected_sha256=PINNED["referenced"]["dy-1730"]["sha256"])
    assert census["complete_events"] == 41 and census["physics_status"] == "withheld"
    assert census["gzip_complete"] and not census["document_complete"] and census["sha256_matches_record"] is False
    record("lhe.kernel.content-truncated", {
        "audit_lhe": {"type": f"{type(audit).__module__}.{type(audit).__qualname__}", "message": str(audit),
                      "position": list(audit.position), "code": audit.code},
        "read_lhe": {"type": type(normalization).__qualname__, "message": str(normalization)},
        "oracle": {"complete_events": census["complete_events"], "physics_withheld_reasons": census["physics_withheld_reasons"]}})


@pytest.mark.kernel_crosscheck
def test_kernel_lhe_readers_on_a_gzip_level_cut(lhe_readers, tmp_path):
    # Documentation (design sections 2 P5 and 8): a cut in the compressed bytes is an EOFError in both
    # kernel readers before any event count is reported; the oracle calls it a truncated stream.
    path, plan = dy_file("dy-1730")
    cut = tmp_path / "cut.lhe.gz"
    cut.write_bytes(path.read_bytes()[:10528])
    audit = kernel_outcome(lambda: lhe_readers["audit_lhe"](cut, plan))
    normalization = kernel_outcome(lambda: lhe_readers["read_lhe"](cut))
    for exc in (audit, normalization):
        assert type(exc) is EOFError and "end-of-stream marker" in str(exc)
    census = lhe_census.census(cut.read_bytes(), selection=SELECTION)
    assert census["stream_error"] == "truncated_stream" and census["physics_status"] == "withheld"
    record("lhe.kernel.gzip-cut", {"audit_lhe": f"EOFError: {audit}", "read_lhe": f"EOFError: {normalization}",
                                   "oracle_stream_error": census["stream_error"]})


# --------------------------------------------------------------------------- diagnostics (design section 7)

# Toys follow the usual LHC prescription: s+b toys at (mu, g_hat(mu)), b-only toys at (0, g_hat(0)), each
# drawing the main count and an integer auxiliary count from Poissons (the observed auxiliary count stays
# the continuous a = tau). CLs = P(q~ >= q~_obs | s+b) / P(q~ >= q~_obs | b). q~ is computed once per
# distinct (count, auxiliary count) pair, which gives exactly the per-toy result.
TOY_CHUNK = 2_000_000
TOY_LARGE_N_SEED = 20260926
TOY_LARGE_N_CHUNKS = int(os.environ.get("RAVEL_ORACLE_TOY_CHUNKS", "3"))
# The 100,000,000-toy record (RAVEL_ORACLE_TOY_CHUNKS=50: seeds 20260926..20260975, numpy 1.26.4):
# toy CLs at the asymptotic observed root, and the implied relative S95 offset, each (value, MC SE).
TOY_REFERENCE = {
    "lf-prior": {"toy_cls": (0.051141, 0.000027), "offset": (0.00468, 0.00011)},
    "lf-v1": {"toy_cls": (0.051293, 0.000036), "offset": (0.00619, 0.00017)},
    "2jl": {"toy_cls": (0.049405, 0.000046), "offset": (-0.00290, 0.00022)},
    "hv": {"toy_cls": (0.050335, 0.000023), "offset": (0.00108, 0.00007)},
}


def toy_setup(model):
    m = counting._SingleBin(model[1], model[2])
    n, a = float(model[0]), m.tau
    s95 = counting.limits(*model)["obs_limit_events"]
    return {"model": model, "m": m, "s95": s95, "q_obs": m.qtilde(s95, n, a, m.free_fit(n, a)),
            "g_mu": m.gamma_hat(s95, n, a), "g_0": m.gamma_hat(0.0, n, a)}


def toy_draws(rng, setup, toys):
    m, s95, g_mu, g_0 = setup["m"], setup["s95"], setup["g_mu"], setup["g_0"]
    return [rng.poisson(s95 + g_mu * m.b, toys), rng.poisson(g_mu * m.tau, toys),
            rng.poisson(g_0 * m.b, toys), rng.poisson(g_0 * m.tau, toys)]


def toy_tail(np, setup, counts, aux):
    """(toys with q~ >= q~_obs, toys with q~ == q~_obs), computing q~ once per distinct (count, aux) pair."""
    m, s95, q_obs = setup["m"], setup["s95"], setup["q_obs"]
    keys, multiplicity = np.unique(counts.astype(np.int64) * 2**32 + aux.astype(np.int64), return_counts=True)
    at_least = ties = 0
    for key, times in zip(keys.tolist(), multiplicity.tolist()):
        k, x = float(key >> 32), float(key & 0xFFFFFFFF)
        q = m.qtilde(s95, k, x, m.free_fit(k, x))
        at_least += times * (q >= q_obs)
        ties += times * (q == q_obs)
    return at_least, ties


def toy_summary(setup, at_least_sb, at_least_b, toys):
    cls_sb, cls_b = at_least_sb / toys, at_least_b / toys
    cls = cls_sb / cls_b
    error = cls * math.sqrt((1 - cls_sb) / (cls_sb * toys) + (1 - cls_b) / (cls_b * toys))
    scale = abs(cls_slope(setup["model"], setup["s95"], 0)) * setup["s95"]   # CLs change per relative S95 change
    return {"s95": setup["s95"], "toy_cls": cls, "cls_sb": cls_sb, "cl_b": cls_b, "mc_standard_error": error,
            "implied_relative_s95_offset": (cls - 0.05) / scale,
            "implied_relative_s95_offset_standard_error": error / scale}


@pytest.mark.diagnostic
def test_toy_cls_at_the_asymptotic_observed_root():
    """20,000 toys per hypothesis (design section 7.3): DIAGNOSTIC only.

    One seeded generator is consumed in the design's model order, which reproduces its scratch values
    exactly. At this N the implied S95 offsets have standard errors of 0.5-1.6 %, so they do not
    resolve the toy-asymptotic difference; test_toy_cls_large_n does.
    """
    np = pytest.importorskip("numpy", reason="numpy draws the toys")
    rng = np.random.default_rng(12345)
    toys = 20000
    out = {}
    for label, model in TOY_MODELS.items():
        setup = toy_setup(model)
        draws = toy_draws(rng, setup, toys)
        (sb, _), (b, _) = toy_tail(np, setup, draws[0], draws[1]), toy_tail(np, setup, draws[2], draws[3])
        out[label] = toy_summary(setup, sb, b, toys)
        # consistent with the large-N toy expectation, which is not 0.05
        reference = TOY_REFERENCE[label]["toy_cls"][0]
        assert abs(out[label]["toy_cls"] - reference) <= 4 * out[label]["mc_standard_error"], (label, out[label])
    if np.__version__ == "1.26.4":      # the recorded environment: the design's 4-digit values reproduce
        assert {k: round(v["toy_cls"], 4) for k, v in out.items()} == \
            {"lf-prior": 0.0502, "lf-v1": 0.0509, "2jl": 0.0508, "hv": 0.0522}
    record("diagnostic.toys", {"toys_per_hypothesis": toys, "seed": 12345, "numpy": np.__version__, "models": out})


@pytest.mark.diagnostic
def test_toy_cls_large_n():
    """Toy CLs at the asymptotic observed root with millions of toys: DIAGNOSTIC only.

    TOY_LARGE_N_CHUNKS chunks of 2,000,000 toys per hypothesis, chunk i drawn from
    numpy.random.default_rng(TOY_LARGE_N_SEED + i); RAVEL_ORACLE_TOY_CHUNKS=50 reproduces the
    100,000,000-toy TOY_REFERENCE record. It measures how far toy-based CLs sits from the asymptotic
    estimand; it does not score anything.
    """
    np = pytest.importorskip("numpy", reason="numpy draws the toys")
    setups = {label: toy_setup(model) for label, model in TOY_MODELS.items()}
    totals = {label: [0, 0, 0] for label in TOY_MODELS}       # s+b tail, b tail, ties
    for chunk in range(TOY_LARGE_N_CHUNKS):
        rng = np.random.default_rng(TOY_LARGE_N_SEED + chunk)
        for label, setup in setups.items():
            draws = toy_draws(rng, setup, TOY_CHUNK)
            (sb, sb_ties), (b, b_ties) = toy_tail(np, setup, draws[0], draws[1]), toy_tail(np, setup, draws[2], draws[3])
            totals[label][0] += sb
            totals[label][1] += b
            totals[label][2] += sb_ties + b_ties
    toys = TOY_LARGE_N_CHUNKS * TOY_CHUNK
    out = {}
    for label, setup in setups.items():
        out[label] = {**toy_summary(setup, totals[label][0], totals[label][1], toys), "ties": totals[label][2]}
        offset, error = out[label]["implied_relative_s95_offset"], out[label]["implied_relative_s95_offset_standard_error"]
        # the observed auxiliary count a = tau lies off the integer toy lattice, so no toy ties q~_obs
        # and the >= and > tail rules agree
        assert out[label]["ties"] == 0
        reference, reference_error = TOY_REFERENCE[label]["offset"]
        assert abs(offset - reference) <= 4 * math.hypot(error, reference_error), (label, out[label])
    # the toy-asymptotic difference is resolved: positive for both likelihood_freshness models
    for label in ("lf-prior", "lf-v1"):
        assert out[label]["implied_relative_s95_offset"] > 4 * out[label]["implied_relative_s95_offset_standard_error"]
    record("diagnostic.toys-large-n", {"toys_per_hypothesis": toys, "chunk": TOY_CHUNK,
                                       "seeds": [TOY_LARGE_N_SEED, TOY_LARGE_N_SEED + TOY_LARGE_N_CHUNKS - 1],
                                       "numpy": np.__version__, "models": out})


@pytest.mark.diagnostic
def test_level_sensitivity_of_the_observed_limit():
    """How far a CLs shift of +-0.002 at the root moves S95 (design section 7.3): DIAGNOSTIC only."""
    out = {}
    for label, model in TOY_MODELS.items():
        base = counting.limits(*model)["obs_limit_events"]
        shifts = [relative(counting.limits(*model, level=level)["obs_limit_events"], base) for level in (0.048, 0.052)]
        assert all(0.005 <= s <= 0.011 for s in shifts), (label, shifts)
        out[label] = {"level_0.048": shifts[0], "level_0.052": shifts[1]}
    record("diagnostic.level-sensitivity", out)


# --------------------------------------------------------------------------- environment

@pytest.mark.kernel_crosscheck
def test_record_crosscheck_environment(pyhf_module):
    import numpy
    import scipy
    try:
        import iminuit                  # the kernel optimizer's fallback minimizer
        iminuit_version = iminuit.__version__
    except ImportError:
        iminuit_version = None
    sources = ["benchmarks/governance/oracle/counting.py", "benchmarks/governance/oracle/lhe_census.py",
               "src/ravel/physics/pyhf_exclude.py", "src/ravel/physics/scoped.py",
               "src/ravel/physics/native_normalization.py", str(TRUNCATED.relative_to(ROOT))]
    record("environment", {
        "python": sys.version.split()[0], "platform": platform.platform(), "pyhf": pyhf_module.__version__,
        "numpy": numpy.__version__, "scipy": scipy.__version__, "iminuit": iminuit_version,
        "sources_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}})
    assert pyhf_module.__version__ == "0.7.6"
