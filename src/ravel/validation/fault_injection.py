"""Measured diagnosis and repair of finite synthetic studies on the ordinary DAG.

Deterministic and caller-supplied proposals share one evaluator. Proposals never
earn credit from their own assertions: a controlled intervention must resolve
the first divergence, graph receipts must show the affected descendants reran,
and an independent likelihood reconstruction must agree. No native tools run.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import secrets
import time

from ravel.validation import fault_injection_study as synthetic
from ravel.workflow import agent_graph as graph
from ravel.workflow.execution import digest, file_hash
from ravel.workflow.state_io import atomic_json, read_json

SCORES = ("detected", "first_stage_located", "discriminating_test", "repaired",
          "affected_descendants_only", "corrected_conclusion", "control_untouched")


def _node(identity, stage, parameters, depends=()):
    return {"id": identity, "kind": "tool", "role": "executor", "depends_on": list(depends),
            "inputs": [], "packet": None, "action": "synthetic-study-stage",
            "parameters": {"stage": stage, "settings": deepcopy(parameters)}, "max_attempts": 1}


def _spec(document, configuration):
    nodes = []
    for arm, settings in (("sample", configuration), ("control", document["rules"])):
        for i, stage in enumerate(synthetic.STAGES):
            nodes.append(_node(f"{arm}-{stage}", stage, settings[stage],
                               [f"{arm}-{synthetic.STAGES[i-1]}"] if i else []))
    return {"schema_version": 1, "graph_id": "synthetic-repair",
            "budget": {"max_nodes": 10, "max_calls": 15, "max_output_tokens": 1,
                       "max_wall_seconds": 120, "max_reworks": 1}, "nodes": nodes}


class _StudyHost:
    """A closed in-memory software operation, accounted by the ordinary graph."""
    def __init__(self, document):
        self.document = deepcopy(document)
        self.identity = {"kind": "synthetic-study", "document_sha256": digest(document),
                         "implementation_sha256": file_hash(Path(synthetic.__file__))}
        self.artifacts = {}
        self.executed = []

    def execute(self, node, request, control):
        def run():
            p = node["parameters"]
            previous = self.artifacts[node["depends_on"][0]] if node["depends_on"] else None
            result = synthetic.execute_stage(p["stage"], p["settings"], deepcopy(previous), self.document)
            self.executed.append(node["id"])
            return result
        value = control.call("synthetic-stage", "tool", request, run)
        self.artifacts[node["id"]] = deepcopy(value)
        return value


def _arm(host, name):
    return {stage: deepcopy(host.artifacts[f"{name}-{stage}"]) for stage in synthetic.STAGES}


def deterministic_proposal(packet):
    """Infer a correction from stage checks and supplied rules, without fault IDs."""
    rows = synthetic.comparisons(packet["study"], packet["artifacts"])
    failed = next((row for row in rows if not row["passed"]), None)
    if failed is None:
        return {"detected": False, "first_stage": None, "test": None, "changes": []}
    stage = failed["stage"]
    settings = packet["configuration"][stage]
    required = packet["study"]["rules"][stage]
    return {"detected": True, "first_stage": stage, "test": synthetic.TESTS[stage],
            "changes": [{"key": k, "value": deepcopy(required[k])} for k in settings
                        if not synthetic.equivalent(settings[k], required[k])]}


def _proposal(value):
    if (type(value) is not dict or set(value) != {"detected", "first_stage", "test", "changes"}
            or type(value["detected"]) is not bool or type(value["changes"]) is not list
            or len(value["changes"]) > 1):
        raise ValueError("proposal requires a boolean detection, first stage, test and at most one setting change")
    if value["first_stage"] is not None and value["first_stage"] not in synthetic.STAGES:
        raise ValueError("proposal names an unknown stage")
    for change in value["changes"]:
        if type(change) is not dict or set(change) != {"key", "value"} or type(change["key"]) is not str:
            raise ValueError("change requires key and JSON value")
    json.dumps(value, allow_nan=False)
    return deepcopy(value)


def _clean(value):
    return value == {"detected": False, "first_stage": None, "test": None, "changes": []}


def _error(exc):
    return {"type": type(exc).__name__, "message": str(exc)[:2000]}


def _intervention(document, configuration, artifacts, proposal):
    """Evaluate one isolated change with identical predecessor and event census."""
    stage = proposal["first_stage"]
    if not proposal["detected"] or stage is None or not proposal["changes"]:
        raise ValueError("a repair needs a detected first stage and one change")
    if proposal["test"] != synthetic.TESTS[stage]:
        raise ValueError("test does not discriminate the proposed stage")
    changed = deepcopy(configuration)
    change = proposal["changes"][0]
    if change["key"] not in changed[stage]:
        raise ValueError("change names an unknown setting")
    # The finite control has one legal source-prescribed value for each setting.
    # Models cannot submit executable code or widen the synthetic study.
    expected = document["rules"][stage][change["key"]]
    if not synthetic.equivalent(change["value"], expected):
        raise ValueError("correction differs from the supplied source rule")
    if synthetic.equivalent(changed[stage][change["key"]], change["value"]):
        raise ValueError("intervention changes nothing")
    changed[stage][change["key"]] = deepcopy(change["value"])
    index = synthetic.STAGES.index(stage)
    previous = artifacts[synthetic.STAGES[index-1]] if index else None
    before = synthetic.execute_stage(stage, configuration[stage], deepcopy(previous), document)
    after = synthetic.execute_stage(stage, changed[stage], deepcopy(previous), document)
    target = synthetic.reference(document)[stage]
    compared = deepcopy(after)
    if stage == "normalization":
        compared.pop("ledger_check")
    successful = not synthetic.equivalent(before, after) and synthetic.equivalent(compared, target)
    return changed, {"test": proposal["test"], "stage": stage, "before": before, "after": after,
                     "predecessor_sha256": digest(previous), "event_census_sha256": digest(document["events"]),
                     "discriminates": successful}


def evaluate_case(outdir, fault_id, *, proposer=deterministic_proposal):
    """Execute one injected fault and matched untouched control; retain all receipts."""
    started = time.monotonic()
    root = Path(outdir)
    if root.exists():
        raise ValueError("evaluation needs a new output directory")
    root.mkdir(parents=True)
    document = synthetic.study()
    configuration = synthetic.inject(document, fault_id)
    fault = next(f for f in synthetic.FAULTS if f["id"] == fault_id)
    plan = _spec(document, configuration)
    engine = _StudyHost(document)
    graph.create(root / "study", plan)
    state = graph.execute(root / "study", engine)
    if not state["complete"]:
        raise RuntimeError("synthetic initial graph did not complete: " + json.dumps(state))
    before, control_before = _arm(engine, "sample"), _arm(engine, "control")
    control_receipts = {k: deepcopy(v) for k, v in state["nodes"].items() if k.startswith("control-")}
    initial_calls = list(engine.executed)
    rows = synthetic.comparisons(document, before)
    reference = synthetic.reference(document)
    scores = dict.fromkeys(SCORES, False)
    error, intervention = None, None
    proposal_errors = {}
    proposal = control_proposal = None
    try:
        # Neither the planted label nor the expected first stage is exposed.
        packets = {
            "sample": {"study": deepcopy(document), "configuration": deepcopy(configuration),
                       "artifacts": deepcopy(before), "available_tests": deepcopy(synthetic.TESTS)},
            "control": {"study": deepcopy(document), "configuration": deepcopy(document["rules"]),
                        "artifacts": deepcopy(control_before), "available_tests": deepcopy(synthetic.TESTS)},
        }
        # Fresh requests alone do not hide an alternating faulty/clean schedule.
        # Draw ordering independently for each paired evaluation, never from its
        # public index or planted label. Deterministic checks need no blinding.
        order = ["sample", "control"]
        if proposer is not deterministic_proposal and secrets.randbelow(2):
            order.reverse()
        proposals = {}
        for arm in order:
            try:
                proposals[arm] = _proposal(proposer(packets[arm]))
            except (ValueError, TypeError, KeyError, IndexError, RuntimeError, OSError) as exc:
                # A refused or failed request stays in the denominator. It must
                # not suppress the matched arm merely because it ran first.
                proposals[arm] = None
                proposal_errors[arm] = _error(exc)
        proposal, control_proposal = proposals["sample"], proposals["control"]
        if proposal_errors:
            error = {"type": "ProposalFailure", "message": "one or more proposal requests failed"}
        if proposal is None:
            raise ValueError("sample proposal unavailable; no correction may be applied")
        scores["detected"] = proposal["detected"]
        scores["first_stage_located"] = proposal["detected"] and proposal["first_stage"] == fault["stage"]
        if proposal["detected"]:
            corrected, intervention = _intervention(document, configuration, before, proposal)
            scores["discriminating_test"] = intervention["discriminates"] and scores["first_stage_located"]
            if scores["discriminating_test"]:
                # Revision binds the corrected setting to the node actually rerun.
                graph.revise(root / "study", _spec(document, corrected), reason="isolated synthetic correction")
                state = graph.execute(root / "study", engine)
                after = _arm(engine, "sample")
                scores["repaired"] = state["complete"] and all(r["passed"] for r in synthetic.comparisons(document, after))
                expected_reruns = [f"sample-{s}" for s in synthetic.STAGES[synthetic.STAGES.index(fault["stage"]):]]
                scores["affected_descendants_only"] = engine.executed[len(initial_calls):] == expected_reruns
                scores["corrected_conclusion"] = state["complete"] and synthetic.equivalent(after["inference"], reference["inference"])
    except (ValueError, TypeError, KeyError, IndexError, RuntimeError, OSError) as exc:
        error = _error(exc)
    final_state = graph.status(root / "study")
    scores["control_untouched"] = (_clean(control_proposal) and _arm(engine, "control") == control_before
        and all(final_state["nodes"][k] == v for k, v in control_receipts.items())
        and all(engine.executed.count(f"control-{s}") == 1 for s in synthetic.STAGES))
    report = {"schema_version": 1, "kind": "synthetic-fault-score", "fault": deepcopy(fault),
              "scores": scores, "proposal": proposal, "control_proposal": control_proposal,
              "checks_before": rows, "intervention": intervention, "error": error,
              "proposal_errors": proposal_errors,
              "before": before["inference"], "after": _arm(engine, "sample")["inference"],
              "reference": reference["inference"], "executed": engine.executed,
              "rerun": engine.executed[len(initial_calls):], "calls": final_state["usage"]["calls"],
              "control_sha256": digest(control_before), "seconds": time.monotonic()-started,
              "execution_authorized": False, "physics_validated": False, "scope": document["scope"]}
    atomic_json(root / "score.json", report)
    return report


def evaluate_suite(outdir, *, proposer=deterministic_proposal, fault_ids=None, mode="deterministic"):
    ids = [f["id"] for f in synthetic.FAULTS] if fault_ids is None else list(fault_ids)
    if not ids or len(ids) != len(set(ids)) or set(ids) - {f["id"] for f in synthetic.FAULTS}:
        raise ValueError("suite requires a unique nonempty known fault population")
    if mode not in ("deterministic", "agent"):
        raise ValueError("suite mode must be deterministic or agent")
    root = Path(outdir)
    if root.exists():
        raise ValueError("evaluation needs a new output directory")
    root.mkdir(parents=True)
    rows = [evaluate_case(Path(outdir)/identity, identity, proposer=proposer) for identity in ids]
    classes = {}
    for row in rows:
        entry = classes.setdefault(row["fault"]["class"], {"total": 0, **dict.fromkeys(SCORES, 0)})
        entry["total"] += 1
        for key in SCORES:
            entry[key] += int(row["scores"][key])
    report = {"schema_version": 1, "kind": "synthetic-fault-suite", "mode": mode,
              "fault_ids": ids, "classes": classes, "rows": rows,
              "physics_validated": False, "execution_authorized": False}
    atomic_json(Path(outdir)/"scores.json", report)
    return report


def score_table(report):
    headers = ("class", "total", *SCORES)
    lines = [" | ".join(headers), " | ".join("---" for _ in headers)]
    lines += [" | ".join([name, str(row["total"]), *(str(row[key]) for key in SCORES)])
              for name, row in sorted(report["classes"].items())]
    return "\n".join(lines)



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--fault", action="append")
    args = parser.parse_args(argv)
    report = evaluate_suite(args.out, fault_ids=args.fault)
    print(score_table(report))
    return int(any(not all(row["scores"].values()) for row in report["rows"]))


if __name__ == "__main__":
    raise SystemExit(main())
