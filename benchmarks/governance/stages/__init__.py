"""RAVEL supervised stage workers for the evaluation broker: fit -> convert -> report.

The workers (fit.py, convert.py, report.py) run under the pinned replay interpreter in
one RAVEL run directory per workspace digest. This module only declares the stage DAG
and builds the supervisor command; it imports nothing outside the standard library.
The supervisor is RAVEL's own ``stage_supervisor.supervise`` with ``resume=True`` and
the declared ``depends_on``, called exactly as its CLI does (errors -> exit 2) but with
a short poll interval: the CLI's fixed 5 s poll would make every executed stage last
at least 5 s. The poll interval is not part of any RAVEL receipt.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ("fit", "convert", "report")
STAGES = {
    "fit": {"kind": "fit", "inputs": ("inputs/workspace.json",), "outputs": ("outputs/fit",),
            "depends_on": (), "artifact": "outputs/fit/fit.json"},
    "convert": {"kind": "conversion", "inputs": ("outputs/fit/fit.json", "inputs/luminosity.json"),
                "outputs": ("outputs/convert",), "depends_on": ("fit",),
                "artifact": "outputs/convert/conversion.json"},
    "report": {"kind": "report", "inputs": ("outputs/convert/conversion.json", "inputs/title.txt"),
               "outputs": ("outputs/report",), "depends_on": ("convert",),
               "artifact": "outputs/report/report.json"},
}
SUPERVISOR = (
    "import json, sys\n"
    "from ravel.workflow.stage_supervisor import supervise\n"
    "a = json.loads(sys.argv[1])\n"
    "try:\n"
    "    code = supervise(a['stage'], a['rundir'], 0, a['log'], a['cmd'], kill_secs=a['kill_secs'],\n"
    "                     poll=a['poll'], inputs=a['inputs'], outputs=a['outputs'],\n"
    "                     depends_on=a['depends_on'], resume=True, cwd=a['rundir'])\n"
    "except (OSError, ValueError) as exc:\n"
    "    print(f'stage_supervisor: {exc}', file=sys.stderr)\n"
    "    code = 2\n"
    "sys.exit(code)\n")


def worker_path(stage):
    return HERE / f"{stage}.py"


def stage_command(python, stage):
    """The supervised command bound into the RAVEL receipt: interpreter, worker script, run dir."""
    return [python, str(worker_path(stage)), "."]


def supervisor_argv(python, stage, rundir, *, kill_secs, poll):
    spec = STAGES[stage]
    request = {"stage": stage, "rundir": str(rundir), "log": f"logs/{stage}.log",
               "cmd": stage_command(python, stage), "inputs": list(spec["inputs"]),
               "outputs": list(spec["outputs"]), "depends_on": list(spec["depends_on"]),
               "kill_secs": float(kill_secs), "poll": float(poll)}
    return [python, "-c", SUPERVISOR, json.dumps(request, sort_keys=True)]
