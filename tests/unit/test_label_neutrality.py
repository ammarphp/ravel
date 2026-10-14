"""T3 label neutrality: names of benchmarks, challenges, tasks and people never change a decision.

Counterfactual pairs add, swap or move such a name. The reading, the plan, its claims and the derived
label must be identical apart from ``identity_context`` (and, for the autonomy pair, the delegation
constraint), compared without offsets, ids or locators. The parts skip until the reader, planner and
derived label land. An AST check keeps identity context and raw request text out of the decision
modules as they land.
"""
import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tests" / "replay"))

import intake_records as ir  # noqa: E402

# Generic context labels only: product tests carry no real benchmark or challenge identity.
LABELS = ("Example evaluation suite, task 3.", "Shared-task submission 12.",
          "Unseen Northern Laboratory Suite, item 41.", "For Dr. Jane Smith's group.")
# Module -> what it may never read. The drafter may read the contract it is given, but never the
# identity context; the label, the plan check and the derivation read neither.
DECISION_MODULES = {"src/ravel/workflow/derived_label.py": ("identity_context", "prompt"),
                    "src/ravel/workflow/request_plan.py": ("identity_context",),
                    "src/ravel/validation/validate_request_plan.py": ("identity_context", "prompt"),
                    "src/ravel/workflow/governance_derivation.py": ("identity_context", "prompt")}
VOCABULARY_DISPLAYS = (ast.Tuple, ast.List, ast.Set)


def _base_prompts():
    cases = ir.load_cases("generic.json", "coverage.json", "probes.json")
    plain = [c["prompt"] for c in cases
             if c["group"] != "boundaries" and c["expect"].get("held") is False and "\n" not in c["prompt"]]
    return plain[::4]


def _pairs():
    ported = {c["id"]: c for c in ir.load_cases("ported.json")}
    pairs = [pytest.param(ported["B14"]["prompt"], ported["B14b"]["prompt"], (), id="B14-B14b"),
             pytest.param(ported["S05"]["prompt"], ported["S05b"]["prompt"], (), id="S05-S05b"),
             pytest.param(ported["B04"]["prompt"], ported["B24"]["prompt"], ("delegation",), id="B04-B24")]
    for i, prompt in enumerate(_base_prompts()):
        label, other = LABELS[i % len(LABELS)], LABELS[(i + 1) % len(LABELS)]
        pairs.append(pytest.param(prompt, f"{label} {prompt}", (), id=f"add-{i}"))
        pairs.append(pytest.param(f"{label} {prompt}", f"{other} {prompt}", (), id=f"swap-{i}"))
        pairs.append(pytest.param(f"{label} {prompt}", f"{prompt} ({label})", (), id=f"move-{i}"))
    return pairs


def _records(intake, prompt):
    reading = intake.read(prompt)
    assert ir.reading_rule_errors(prompt, reading) == []
    plan = label = None
    if intake._draft is not None:
        plan = intake.plan(reading, intake.contract(prompt))
        if intake._derive is not None:
            label = intake.label(reading, plan)
    return reading, plan, label


@pytest.mark.parametrize("base,variant,also_ignored", _pairs())
def test_identity_names_do_not_change_the_reading_plan_or_label(base, variant, also_ignored):
    intake = ir.Intake()
    intake.require("reader")
    ignore = ("identity_context",) + tuple(also_ignored)
    a, b = _records(intake, base), _records(intake, variant)
    pa = ir.neutral_projection(*a, ignore_constraints=ignore)
    pb = ir.neutral_projection(*b, ignore_constraints=ignore)
    assert ir.projection_hash(pa) == ir.projection_hash(pb), {k: (pa[k], pb[k]) for k in pa if pa[k] != pb[k]}
    for prompt, (reading, _, _) in ((base, a), (variant, b)):
        for label in LABELS:
            if label in prompt and not also_ignored:
                window = ir.locate(prompt, label.rstrip("."))
                context = [c for c in reading["constraints"] if c["type"] == "identity_context"]
                assert ir.evidence_overlapping(context, window), f"{label!r} is not recorded as identity context"


def test_the_question_fact_keeps_identity_labels_out_of_its_value_and_evidence():
    from ravel.workflow import request_reading
    question = "Check whether the anomaly cancellation conditions hold for a U(1)_{B-L} extension."
    for text in (question, f"{LABELS[1]} {question}", f"{question} ({LABELS[1]})", f"{LABELS[3]} {question}"):
        rows = [f for f in request_reading.document(text)["facts"] if f["type"] == "question_form"]
        assert len(rows) == 1, text
        assert rows[0]["value"]["text"] == question
        assert [e["text"] for e in rows[0]["evidence"]] == [question]


def identity_reads(source):
    """Lines where a module reads identity context or raw request text."""
    tree = ast.parse(source)
    displays = {id(elt) for node in ast.walk(tree) if isinstance(node, VOCABULARY_DISPLAYS) for elt in node.elts}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "identity_context" and id(node) not in displays:
            found.append((node.lineno, "identity_context"))
        key = None
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            key = node.slice.value
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get"
              and node.args and isinstance(node.args[0], ast.Constant)):
            key = node.args[0].value
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            key = node.attr
        if key == "prompt":
            found.append((node.lineno, "prompt"))
    return sorted(set(found))


def test_identity_read_detector():
    source = ("VOCAB = ('identity_context', 'blinding')\n"
              "def f(reading, contract):\n"
              "    a = [c for c in reading['constraints'] if c['type'] == 'identity_context']\n"
              "    b = contract['prompt']\n"
              "    c = contract.get('prompt')\n"
              "    return a, b, c\n")
    assert identity_reads(source) == [(3, "identity_context"), (4, "prompt"), (5, "prompt")]


@pytest.mark.parametrize("relative,forbidden", sorted(DECISION_MODULES.items()))
def test_decision_modules_never_read_identity_context_or_request_text(relative, forbidden):
    path = REPO / relative
    if not path.is_file():
        pytest.skip(f"{relative} has not landed")
    reads = [r for r in identity_reads(path.read_text(encoding="utf-8")) if r[1] in forbidden]
    assert not reads, f"{relative} reads identity context or raw request text at {reads}"
