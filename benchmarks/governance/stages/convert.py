"""Stage 'convert': visible cross-section limits sigma_vis = S95 / L from the fit and a luminosity record.

The arithmetic is the scoped worker's conversion rule (ravel.physics.scoped.likelihood):
each limit is divided by the luminosity only when its status is ``resolved``, otherwise
it is null. The luminosity record is a JSON object with a finite positive
``luminosity_fb``. Runs only under the RAVEL stage supervisor.
"""
import math
import os
import sys
from pathlib import Path

STAGE = "convert"


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json, read_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        fit = read_json(rd / "outputs/fit/fit.json")
        record = read_json(rd / "inputs/luminosity.json")
        lumi = record.get("luminosity_fb") if isinstance(record, dict) else None
        if type(lumi) not in (int, float) or not math.isfinite(lumi) or lumi <= 0:
            raise ValueError("the luminosity record requires a finite positive luminosity_fb")
        status = fit["limit_status"]
        atomic_json(out / "conversion.json", {
            "schema_version": 1,
            "luminosity_fb": lumi,
            "sigma_vis_obs_fb": fit["obs_limit_events"] / lumi if status["observed"] == "resolved" else None,
            "sigma_vis_exp_fb": [v / lumi if state == "resolved" else None
                                 for v, state in zip(fit["exp_limits_events"], status["expected"])],
            "obs_limit_events": fit["obs_limit_events"],
            "exp_limits_events": fit["exp_limits_events"],
            "limit_status": status,
            "formula": "sigma_vis = S95 / L"})
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
