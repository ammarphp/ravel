"""Stage 'fit': 95% CLs signal-event limits of the supplied likelihood with the RAVEL kernel.

Replicates the scoped likelihood worker (ravel.physics.scoped.likelihood) exactly:
prepare_workspace's mandatory numerical-interface checks (free normfactor POI, bounds
[0, >= poi_cap], finite data, POI changes the expectation), the numpy backend with
robust_optimizer(tolerance=1e-9) at 64-bit precision, and compute(model, data,
poi_cap=..., diagnostic_record=...). Runs only under the RAVEL stage supervisor.
Writes outputs/fit/fit.json (the deterministic broker artifact) plus the full kernel
result and fit diagnostics beside it.
"""
import os
import sys
from pathlib import Path

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

STAGE = "fit"
POI_CAP = 256.0   # slice design §5 (PROVISIONAL); common to every arm
LEVEL = 0.05


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        import pyhf
        from ravel.physics.pyhf_exclude import compute, robust_optimizer
        from ravel.physics.scoped import prepare_workspace
        workspace = prepare_workspace({"likelihood": {"workspace": "inputs/workspace.json",
                                                      "poi_cap": POI_CAP}}, rd)
        ws = pyhf.Workspace(workspace)
        model = ws.model(measurement_name=None)
        data = ws.data(model)
        pyhf.set_backend("numpy", robust_optimizer(tolerance=1e-9), precision="64b")
        diagnostics = {}
        try:
            result = compute(model, data, poi_cap=POI_CAP, diagnostic_record=diagnostics)
        finally:
            atomic_json(out / "fit-diagnostics.json", diagnostics)
        atomic_json(out / "kernel-result.json", result)
        status = result["limit_status"]
        atomic_json(out / "fit.json", {
            "schema_version": 1,
            "obs_limit_events": float(result["obs_limit"]),
            "exp_limits_events": [float(v) for v in result["exp_limits"]],
            "limit_status": {"observed": str(status["observed"]),
                             "expected": [str(v) for v in status["expected"]]},
            "flags": {name: bool(result[name]) for name in
                      ("at_poi_cap", "median_at_cap", "at_mu_floor", "band_degenerate", "cls_monotonic")},
            "poi_cap": POI_CAP, "level": LEVEL, "test_statistic": "qtilde",
            "calculation": "asymptotic_cls", "pyhf_version": pyhf.__version__})
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
