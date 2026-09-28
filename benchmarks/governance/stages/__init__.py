"""RAVEL supervised stage workers for the evaluation broker.

Two groups of workers run under the pinned replay interpreter:

- The likelihood DAG, fit -> convert -> report (fit.py, convert.py, report.py), runs in one RAVEL
  run directory per workspace digest (``ravel-runs/<first 16 hex of its sha256>/``): the DAG's
  root input keys the directory, the luminosity record and title are placed there per call, and
  RAVEL's receipts decide which stages are reused.
- The standalone stages census, calc and figure (census.py, calc.py, figure.py; WP12 task-bank
  design §3.3) run each in a run directory keyed by the stage, its input digests and its
  parameters (``run_key``; calc and figure take theirs as ``inputs/params.json``): the input files
  are placed once and never change, so a repeated request is a verified reuse. ``figure`` is a
  coordinator-only prior-recipe step (``COORDINATOR_ONLY``); no subject operation runs it.

This module only declares the stages and builds the supervisor command; it imports nothing outside
the standard library. The supervisor is RAVEL's own ``stage_supervisor.supervise`` with
``resume=True`` and the declared ``depends_on``, called exactly as its CLI does (errors -> exit 2)
but with a short poll interval: the CLI's fixed 5 s poll would make every executed stage last at
least 5 s. The poll interval is not part of any RAVEL receipt.
"""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ("fit", "convert", "report")            # the likelihood DAG, in dependency order
STANDALONE = ("census", "calc", "figure")       # one keyed run directory per (stage, inputs, parameters)
COORDINATOR_ONLY = ("figure",)                  # prior-recipe steps no subject operation may run
WORKERS = ORDER + STANDALONE
PARAMS = "inputs/params.json"
STAGES = {
    "fit": {"kind": "fit", "inputs": ("inputs/workspace.json",), "outputs": ("outputs/fit",),
            "depends_on": (), "artifact": "outputs/fit/fit.json"},
    "convert": {"kind": "conversion", "inputs": ("outputs/fit/fit.json", "inputs/luminosity.json"),
                "outputs": ("outputs/convert",), "depends_on": ("fit",),
                "artifact": "outputs/convert/conversion.json"},
    "report": {"kind": "report", "inputs": ("outputs/convert/conversion.json", "inputs/title.txt"),
               "outputs": ("outputs/report",), "depends_on": ("convert",),
               "artifact": "outputs/report/report.json"},
    "census": {"kind": "census", "inputs": ("inputs/events.lhe.gz", "inputs/manifest.json", "inputs/selection.json"),
               "outputs": ("outputs/census",), "depends_on": (), "artifact": "outputs/census/census.json"},
    "calc": {"kind": "calc", "inputs": (PARAMS,), "outputs": ("outputs/calc",), "depends_on": (),
             "artifact": "outputs/calc/calc.json"},
    "figure": {"kind": "figure", "inputs": ("inputs/fit.json", PARAMS), "outputs": ("outputs/figure",),
               "depends_on": (), "artifact": "outputs/figure/figure.json"},
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


def params_bytes(params) -> bytes:
    """The canonical JSON bytes (governance.canonical's) of a standalone stage's parameters (``inputs/params.json``)."""
    return json.dumps(params, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=True).encode()


def run_key(stage, files) -> str:
    """The run-directory name of a standalone stage: the first 16 hex of the sha256 of its name and the sha256
    of every input file it is given ({relative path: bytes}, parameters included as ``inputs/params.json``)."""
    if stage not in STANDALONE:
        raise ValueError(f"{stage} is not a standalone stage")
    if set(files) != set(STAGES[stage]["inputs"]):
        raise ValueError(f"{stage} takes exactly the inputs {sorted(STAGES[stage]['inputs'])}")
    material = {"stage": stage, "inputs": {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}}
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def supervisor_argv(python, stage, rundir, *, kill_secs, poll):
    spec = STAGES[stage]
    request = {"stage": stage, "rundir": str(rundir), "log": f"logs/{stage}.log",
               "cmd": stage_command(python, stage), "inputs": list(spec["inputs"]),
               "outputs": list(spec["outputs"]), "depends_on": list(spec["depends_on"]),
               "kill_secs": float(kill_secs), "poll": float(poll)}
    return [python, "-c", SUPERVISOR, json.dumps(request, sort_keys=True)]
