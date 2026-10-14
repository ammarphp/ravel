"""T1 legacy identity: what today's code decides for every fixture v1 contract.

For each contract the snapshot records ``validate_task_contract.validate``, ``required_stages``,
``checkin_variant``, ``approval_input_paths``, ``verify_approval`` and ``evaluate``. Paths are
normalised (``<RUNDIR>``, ``<ROOT>``, ``<REPO>``) and the record is hashed. A golden file pins those hashes, so
any change that alters a decision for an existing contract fails ``test_legacy_identity.py`` until
it is re-recorded deliberately:

    python tests/unit/legacy_identity.py record

The fixture contracts are synthetic: every task mode and compute plan, on both sides of the gate
epoch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from ravel.validation import validate_checkin, validate_run_state, validate_task_contract  # noqa: E402
from ravel.workflow import workflow_state  # noqa: E402

GOLDEN_DIR = REPO / "tests" / "fixtures" / "legacy-identity"
GOLDEN = {"fixtures": GOLDEN_DIR / "fixtures.json"}
# Rundir names on either side of the gate epoch (validate_run_state.GATE_EPOCH, 2026-07-08).
FIXTURE_DATES = ("2026-07-01", "2026-10-11")


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def rundir_of(contract_path):
    parent = Path(contract_path).parent
    return parent.parent if parent.name == "inputs" else parent


def _call(fn, *args, **kwargs):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return {"value": fn(*args, **kwargs)}
    except Exception as exc:  # the identity of a refusal is part of the record
        return {"raised": type(exc).__name__, "message": str(exc)}


def _canonical(value):
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_canonical(v) for v in value), key=repr)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def snapshot(contract_path, root=None):
    """The normalised decision record for one contract, and its hash.

    ``root`` is the checkout the run belongs to; paths under it become ``<ROOT>``.
    """
    rundir = rundir_of(contract_path)
    loaded = _call(validate_task_contract.load_contract, str(contract_path))
    contract = loaded.get("value")
    record = {
        "load": {k: v for k, v in loaded.items() if k != "value"},
        "validate": _call(validate_task_contract.validate, contract),
        "required_stages": _call(validate_run_state.required_stages, contract),
        "checkin_variant": _call(validate_checkin.checkin_variant, contract),
        "approval_input_paths": _call(workflow_state.approval_input_paths, str(rundir)),
        "verify_approval": _call(workflow_state.verify_approval, str(rundir)),
        "evaluate": _call(validate_run_state.evaluate, str(rundir), contract),
    }
    text = json.dumps(_canonical(record), sort_keys=True)
    root = Path(root or REPO)
    for path, label in ((rundir, "<RUNDIR>"), (root, "<ROOT>"), (REPO, "<ROOT>" if root == REPO else "<REPO>")):
        for form in {os.path.realpath(path), str(path)}:
            text = text.replace(form, label)
    verdict = (record["evaluate"].get("value") or {}).get("verdict") if isinstance(
        record["evaluate"].get("value"), dict) else None
    return {"record": _sha(text.encode()), "verdict": verdict}, text


def build_fixture_runs(base):
    """Fixture contracts: every task mode x compute plan, on both sides of the gate epoch."""
    runs = {}
    for task_mode in validate_task_contract.TASK_MODES:
        for plan in validate_task_contract.COMPUTE_PLANS:
            for date in FIXTURE_DATES:
                name = f"{date}_fixture-{task_mode}-{plan}"
                rundir = Path(base) / name
                (rundir / "inputs").mkdir(parents=True)
                contract = validate_run_state._base_contract(task_mode=task_mode, compute_plan=plan)
                (rundir / "inputs" / "task_contract.json").write_text(json.dumps(contract, indent=2))
                runs[name] = rundir / "inputs" / "task_contract.json"
    return runs


def observe(kind="fixtures"):
    """{key: entry} for the fixture contracts, plus an empty list of keys whose evaluation wrote to inputs."""
    if kind != "fixtures":
        raise ValueError(f"unknown golden kind: {kind}")
    entries = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, path in build_fixture_runs(tmp).items():
            entries[name] = snapshot(path, tmp)[0]
    return entries, []


def record():
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    entries = observe("fixtures")[0]
    doc = {"schema_version": 1, "recorded_at": head, "entries": entries}
    GOLDEN["fixtures"].write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    print(f"fixtures: {len(entries)} contracts -> {GOLDEN['fixtures'].relative_to(REPO)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["record"])
    parser.parse_args()
    record()
