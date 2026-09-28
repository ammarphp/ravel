"""Stage 'figure': a summary-figure record of a fit (WP12 design §2 P6; coordinator-only).

A prior-recipe step only the coordinator runs (``stages.COORDINATOR_ONLY``): no subject operation reaches
it. Inputs in the run directory: ``inputs/fit.json`` (the content of the fit artifact the broker cites)
and ``inputs/params.json``, the legend mapping ``{legend: [{series, label, field}, ...]}``: each entry names
a plotted series (``solid`` or ``dashed``), its legend label and the fit field it plots
(``obs_limit_events`` or ``exp_limits_events[0..4]``). The mapping is taken as given, so a figure can be
fresh and still wrong (a legend that swaps the observed and expected series).

Writes ``outputs/figure/figure.json``: ``{schema_version, figure: "CLs scan", legend: [{series, label,
limit_events}], note}``, each ``limit_events`` the plotted value as text with 4 significant digits. A field
whose limit status is not ``resolved`` is refused. Runs only under the RAVEL stage supervisor.
"""
import math
import os
import re
import sys
from pathlib import Path

STAGE = "figure"
SERIES = ("solid", "dashed")
NOTE = "synthetic development fixture"
FIELD = re.compile(r"obs_limit_events|exp_limits_events\[([0-4])\]")
MAX_LABEL = 80


def require_supervised(rd):
    from ravel.workflow.execution import load_execution
    record = load_execution(rd)["stages"].get(STAGE, {})
    if record.get("status") != "running" or record.get("supervisor_pid") != os.getppid():
        raise SystemExit(f"{STAGE} worker must be launched by the RAVEL stage supervisor")


def plotted(fit, field):
    """The fit's resolved value of one legend field."""
    match = FIELD.fullmatch(field) if isinstance(field, str) else None
    if match is None:
        raise ValueError("a legend field is obs_limit_events or exp_limits_events[0..4]")
    if match.group(1) is None:
        value, status = fit["obs_limit_events"], fit["limit_status"]["observed"]
    else:
        index = int(match.group(1))
        value, status = fit["exp_limits_events"][index], fit["limit_status"]["expected"][index]
    if status != "resolved" or type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{field}: the fit's value is not a resolved limit")
    return value


def figure(fit, params):
    if not isinstance(params, dict) or set(params) != {"legend"}:
        raise ValueError("figure parameters are exactly {legend}")
    legend = params["legend"]
    if not isinstance(legend, list) or [e.get("series") if isinstance(e, dict) else None for e in legend] != \
            list(SERIES):
        raise ValueError(f"the legend has one entry per series, in the order {list(SERIES)}")
    entries = []
    for entry in legend:
        if set(entry) != {"series", "label", "field"}:
            raise ValueError("a legend entry is exactly {series, label, field}")
        label = entry["label"]
        if not (isinstance(label, str) and label.strip() and len(label) <= MAX_LABEL and "\n" not in label):
            raise ValueError(f"a legend label is one nonblank line of at most {MAX_LABEL} characters")
        entries.append({"series": entry["series"], "label": label,
                        "limit_events": f"{plotted(fit, entry['field']):.4g}"})
    return {"schema_version": 1, "figure": "CLs scan", "legend": entries, "note": NOTE}


def main():
    rd = Path(sys.argv[1]).resolve()
    require_supervised(rd)
    from ravel.workflow.state_io import atomic_json, read_json
    out = rd / "outputs" / STAGE
    out.mkdir(parents=True, exist_ok=False)
    try:
        record = figure(read_json(rd / "inputs/fit.json"), read_json(rd / "inputs/params.json"))
        atomic_json(out / "figure.json", record)
    except Exception as exc:
        atomic_json(out / "failure.json", {"type": type(exc).__name__, "error": str(exc)})
        raise


if __name__ == "__main__":
    main()
