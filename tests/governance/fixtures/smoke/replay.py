"""SYNTHETIC replay of the 8 sealed smoke runs for the evaluator regression cases (README.md beside this file).

``replay(campaign, case)`` rebuilds one run in a synthetic builder campaign (fixtures/sealed/builder.py, its own
synthetic broker secret): the development family's input bytes with the smoke task's current title, the smoke kernel's
stage contents (``tasks.json``), and the subject's recorded operations, submissions (evidence handles mapped from their
symbols), recorded guard diagnostics and final message, then seals it. Not agent evidence: a software-test fixture.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("sealed_fixture_builder_smoke", HERE.parent / "sealed" / "builder.py")
builder = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(builder)

INPUTS = {"workspace": "workspace.json", "luminosity": "luminosity.json", "title": "title.txt"}


def cases() -> list:
    """The regression cases in launch order (run-<n>-<task>-<arm>.json)."""
    paths = sorted(HERE.glob("run-*.json"), key=lambda p: int(p.name.split("-")[1]))
    return [json.loads(p.read_text()) for p in paths]


def smoke_tasks(out_dir) -> dict:
    """{task_id: {definition, oracle, current, prior, stage_contents}}: the development family's input files, with the
    smoke task's current title; every input's sha256 must equal the smoke oracle's (fails loudly on a drift)."""
    _, family = builder.build_family(out_dir)
    recorded = json.loads((HERE / "tasks.json").read_text())
    tasks = {}
    for task_id, record in recorded.items():
        current = {**family[task_id]["current"], "title.txt": record["current_title"].encode("utf-8")}
        prior = dict(family[task_id]["prior"])
        for side, files in (("current", current), ("prior", prior)):
            shas = {name: builder.canonical.sha256_bytes(data) for name, data in files.items()}
            wanted = record["oracle"][side]["inputs"]
            assert all(shas[name] == sha for name, sha in wanted.items()), (task_id, side, shas, wanted)
        tasks[task_id] = {"definition": record["definition"], "oracle": record["oracle"], "current": current,
                          "prior": prior, "stage_contents": record["stage_contents"]}
    return tasks


def campaign(root, out_dir):
    """A synthetic campaign over the smoke's two task definitions (lf-b, lf-d)."""
    tasks = smoke_tasks(out_dir)
    index = {"v1_tasks": [{"id": task_id, "expected": t["definition"]["expected"],
                           "prompt_sha256": t["definition"]["prompt_sha256"],
                           "oracle_sha256": t["definition"]["oracle_sha256"],
                           "fidelity_tolerance": t["definition"]["fidelity"]["tolerance"]}
                          for task_id, t in sorted(tasks.items())]}
    return builder.Campaign(root, index, tasks)


class ReplayRun(builder.Run):
    """A builder run whose kernel outputs are the smoke kernel's recorded stage contents."""

    def stage_content(self, kind, derived):
        for entry in self.campaign.tasks[self.task_id]["stage_contents"]:
            if entry["kind"] == kind and entry["derived_from"] == derived:
                return copy.deepcopy(entry["content"])
        raise KeyError(f"no recorded {kind} content for {derived}")


def replay(camp, case):
    """Rebuild and seal one smoke run; returns the builder run."""
    run = ReplayRun(camp, case["task_id"], case["arm"], "reference")
    handles = {f"current:{kind}": value["handle"] for kind, value in run.current.items()}
    handles.update({f"prior:{kind}": handle for kind, handle in run.prior.items()})
    handles.update({f"prior:{record['kind']}": handle for handle, record in run.artifacts.items()
                    if record["origin"] == "prior" and record["kind"] in INPUTS})

    def resolve(symbol):
        return handles.get(symbol, symbol)

    for step in case["steps"]:
        op = step["op"]
        if op == "inputs":
            run.op_inputs()
        elif op in ("status", "note"):
            run._line(op, {}, result={})
        elif op == "show" and step["ok"]:
            run.op_show(resolve(step["handle"]))
        elif op == "submit_invalid":
            run.submit_invalid()
        elif op == "submit":
            submission = step["submission"]
            claims = [{**claim, "evidence_ids": [resolve(h) for h in claim["evidence_ids"]]}
                      for claim in submission["claims"]]
            diagnostics = [{**d, **({"handle": resolve(d["handle"])} if "handle" in d else {})}
                           for d in step["diagnostics"]]
            refusal = submission["refusal"]["text"] if submission["refusal"] is not None else None
            _, accepted = run.submit(claims, submission["report_text"], refusal=refusal, final=submission["final"],
                                     diagnostics=diagnostics)
            assert accepted == step["recorded"]["accepted"], (case["case"], step["recorded"])
        elif op in ("fit", "convert", "report") and step["ok"]:
            args = {k: resolve(v) for k, v in step["args"].items()}
            if op == "fit":
                made = run.op_fit(args["workspace"], status=step["status"])
            elif op == "convert":
                made = run.op_convert(args["fit"], args["luminosity"], status=step["status"],
                                      upstream_fit=step["upstream"][0]["status"])
            else:
                made = run.op_report(args["conversion"], args["title"], status=step["status"])
            handles[step["produces"]] = made
        else:                                   # a failed show or stage call: the broker refused it
            args = {"handle": resolve(step["handle"])} if op == "show" else \
                {k: resolve(v) for k, v in step["args"].items()}
            run._line(op, args, ok=False, error_code=step["error_code"], result=None)
    run.seal(case["final_text"])
    return run
