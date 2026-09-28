"""Stage 'fit': 95% CLs signal-event limits of the supplied likelihood with the RAVEL kernel.

Replicates the scoped likelihood worker (ravel.physics.scoped.likelihood): prepare_workspace's
mandatory numerical-interface checks (free normfactor POI, bounds [0, >= poi_cap], finite data, POI
changes the expectation), the numpy backend with robust_optimizer(tolerance=1e-9) at 64-bit
precision, and compute(model, data, poi_cap=..., diagnostic_record=...). Runs only under the RAVEL
stage supervisor.

Generalized for the WP12 task bank (design §3.3): ``poi_cap`` is the upper bound the supplied
workspace declares for its parameter of interest (pyhf's own bound, so an undeclared normfactor bound
is pyhf's default), never a stage constant, and the model is built with the kernel's
``MODIFIER_SETTINGS`` passed explicitly (normsys code4, histosys code4p; a counting model has neither,
so its numbers do not change). A curve whose CLs never falls to the level inside [0, poi_cap] keeps
the kernel's status (``above_scan``) and its bound; ``cls_at_cap_obs`` and ``cls_at_cap_exp`` then
give the kernel's CLs at mu = poi_cap for exactly those curves (null for a curve that resolved, and
both null when no curve is above the scan). For the likelihood_freshness workspaces (POI range
[0, 256]) every value is unchanged and both new fields are null.

Writes outputs/fit/fit.json (the deterministic broker artifact) plus the full kernel result and fit
diagnostics beside it.
"""
import os
import sys
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

STAGE = "fit"
LEVEL = 0.05
ABOVE = "above_scan"


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def declared_poi_cap(workspace, modifier_settings):
    """The upper bound the workspace declares for its parameter of interest (a finite positive float)."""
    import math
    import pyhf
    ws = pyhf.Workspace(workspace)
    if len(ws.measurement_names) > 1:
        raise ValueError("multiple measurements require explicit measurement selection")
    model = ws.model(measurement_name=None, modifier_settings=modifier_settings)
    index = model.config.poi_index
    if index is None:
        raise ValueError("likelihood requires a free scalar POI")
    cap = float(model.config.suggested_bounds()[index][1])
    if not math.isfinite(cap) or cap <= 0:
        raise ValueError("the workspace's POI upper bound must be finite and positive")
    return cap


def cls_at_cap(result, cap):
    """(observed, expected[5]) CLs at mu = cap for the curves above the scan, or (None, None) when there are none."""
    status = result["limit_status"]
    above = [status["observed"] == ABOVE] + [s == ABOVE for s in status["expected"]]
    if not any(above):
        return None, None
    if not result["scan_mu"] or float(result["scan_mu"][-1]) != cap:
        raise ValueError("a curve is above the scan but the kernel's scan does not end at the POI cap")
    last = [float(result["scan_cls_obs"][-1]), *(float(v) for v in result["scan_cls_exp"][-1])]
    values = [value if flag else None for value, flag in zip(last, above)]
    return values[0], values[1:]


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json, read_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        import pyhf
        from ravel.physics.pyhf_exclude import MODIFIER_SETTINGS, compute, robust_optimizer
        from ravel.physics.scoped import prepare_workspace
        poi_cap = declared_poi_cap(read_json(rd / "inputs/workspace.json"), MODIFIER_SETTINGS)
        workspace = prepare_workspace({"likelihood": {"workspace": "inputs/workspace.json",
                                                      "poi_cap": poi_cap}}, rd)
        ws = pyhf.Workspace(workspace)
        model = ws.model(measurement_name=None, modifier_settings=MODIFIER_SETTINGS)
        data = ws.data(model)
        pyhf.set_backend("numpy", robust_optimizer(tolerance=1e-9), precision="64b")
        diagnostics = {}
        try:
            result = compute(model, data, poi_cap=poi_cap, diagnostic_record=diagnostics)
        finally:
            atomic_json(out / "fit-diagnostics.json", diagnostics)
        atomic_json(out / "kernel-result.json", result)
        status = result["limit_status"]
        observed_at_cap, expected_at_cap = cls_at_cap(result, poi_cap)
        atomic_json(out / "fit.json", {
            "schema_version": 1,
            "obs_limit_events": float(result["obs_limit"]),
            "exp_limits_events": [float(v) for v in result["exp_limits"]],
            "limit_status": {"observed": str(status["observed"]),
                             "expected": [str(v) for v in status["expected"]]},
            "flags": {name: bool(result[name]) for name in
                      ("at_poi_cap", "median_at_cap", "at_mu_floor", "band_degenerate", "cls_monotonic")},
            "cls_at_cap_obs": observed_at_cap, "cls_at_cap_exp": expected_at_cap,
            "poi_cap": poi_cap, "level": LEVEL, "test_statistic": "qtilde",
            "calculation": "asymptotic_cls", "pyhf_version": pyhf.__version__})
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
