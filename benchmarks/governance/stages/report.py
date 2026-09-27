"""Stage 'report': render the visible cross-section limit report from a conversion and a title.

The report states the observed and median expected limits (5 significant digits) and
the luminosity used; the artifact also carries every converted value. Runs only under
the RAVEL stage supervisor.
"""
import os
import sys
from pathlib import Path

STAGE = "report"
UNRESOLVED = "not resolved (numerical bound only)"


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def limit(value):
    return UNRESOLVED if value is None else f"{value:.5g} fb"


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json, read_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        conversion = read_json(rd / "outputs/convert/conversion.json")
        title = (rd / "inputs/title.txt").read_text(encoding="utf-8").strip()
        if not title:
            raise ValueError("the title input is blank")
        text = "\n".join([
            f"# {title}", "",
            f"Observed 95% CLs upper limit on the visible cross section: {limit(conversion['sigma_vis_obs_fb'])}.",
            "Median expected 95% CLs upper limit on the visible cross section: "
            f"{limit(conversion['sigma_vis_exp_fb'][2])}.", "",
            f"sigma_vis = S95 / L with integrated luminosity L = {conversion['luminosity_fb']:g} fb^-1, where S95 "
            "is the asymptotic qtilde CLs upper limit on the number of signal events of the supplied "
            "counting likelihood.", ""])
        atomic_json(out / "report.json", {
            "schema_version": 1, "title": title, "text": text,
            **{key: conversion[key] for key in ("sigma_vis_obs_fb", "sigma_vis_exp_fb", "luminosity_fb",
                                                "obs_limit_events", "exp_limits_events", "limit_status")}})
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
