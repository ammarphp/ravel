#!/usr/bin/env python3
"""Bounded installed-CLI integration checks; explicit experimental assent required.

Four statistical attempts (one deliberately fails); optionally four 100-event
native attempts, sequential and each capped at 120 seconds. No tool installation.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--native-spec", type=Path)
    ap.add_argument("--scripted-yes", action="store_true", required=True,
                    help="only use under explicit user authorization for experimental assent")
    args = ap.parse_args()
    rd = args.out.expanduser().resolve()
    rd.mkdir(parents=True, exist_ok=False)
    records = []

    def command(label, *parts, success=True):
        cmd = [sys.executable, "-B", "-m", "ravel", *map(str, parts)]
        start = time.monotonic()
        result = subprocess.run(cmd, cwd=rd, capture_output=True, text=True, timeout=150)
        record = {"label": label, "command": cmd, "returncode": result.returncode,
                  "seconds": time.monotonic() - start,
                  "expected_success": success, "passed": (result.returncode == 0) == success}
        (rd / f"{len(records):02d}-{label}.log").write_text(result.stdout + result.stderr)
        records.append(record)
        write(rd / "commands.json", records)
        if not record["passed"]:
            raise RuntimeError(f"{label} returned unexpected {result.returncode}; inspect retained log")
        return result

    def run(name, spec, *, success=True):
        path = rd / name
        spec = deepcopy(spec)
        spec.update(approval_mode="scripted_yes", max_seconds=120)
        write(rd / f"{name}.json", spec)
        prompt = ("Generate a generation-only parton-level control using the explicit supplied specification."
                  if spec["mode"] == "generate" else "Compute a likelihood-only control from the explicit supplied model.")
        command(name + "-intake", "initiate", "--prompt", prompt, "--out", path)
        command(name + "-plan", "plan", "--rundir", path, "--spec", rd / f"{name}.json")
        # The experiment declares YES only after the concrete plan is available.
        checkin = path / "inputs/checkin1.json"
        approval = "YES under the explicitly authorized scripted experimental policy to CHECK-IN 1 SHA256 " + hashlib.sha256(checkin.read_bytes()).hexdigest()
        command(name + "-approve", "approve", "--rundir", path, "--scripted", "--quote", approval)
        command(name + "-run", "run", "--rundir", path, success=success)
        state = command(name + "-status", "status", "--rundir", path, "--write", success=success)
        packet = json.loads(state.stdout)
        if (packet["lifecycle_verdict"] == "PASS") != success:
            raise AssertionError(f"{name}: lifecycle disagrees with delivered outcome")
        if success:
            ledger_before = (path / "execution_state.json").read_bytes()
            command(name + "-resume", "run", "--rundir", path, "--resume")
            assert (path / "execution_state.json").read_bytes() == ledger_before, "resume spent another attempt"
        else:
            command(name + "-retry-refused", "run", "--rundir", path, "--resume", success=False)
        return path

    spec = json.loads((Path(__file__).parent / "atlas-2jl-counting.json").read_text())
    counting = run("counting", spec)
    counting_b = run("counting-replica", spec)
    command("same-likelihood", "compare-recipes", "--left", counting, "--right", counting_b,
            "--out", rd / "same-likelihood.json")
    # A distinct two-bin model with binwise auxiliary constraints and a shared
    # luminosity nuisance exercises supplied-workspace routing and normalization.
    import pyhf
    model = pyhf.simplemodels.uncorrelated_background(signal=[5., 10.], bkg=[20., 40.], bkg_uncertainty=[4., 6.])
    channels = deepcopy(model.spec["channels"])
    channels[0]["samples"][0]["modifiers"].append(
        {"name": "luminosity", "type": "normsys", "data": {"lo": .97, "hi": 1.03}})
    workspace = {"version": "1.0.0", "channels": channels,
        "observations": [{"name": "singlechannel", "data": [21., 38.]}],
        "measurements": [{"name": "control", "config": {"poi": "mu",
            "parameters": [{"name": "mu", "bounds": [[0, 32]], "inits": [1]}]}}]}
    write(rd / "two-bin-workspace.json", workspace)
    generic = deepcopy(spec)
    generic["source"] = "Declared synthetic two-bin workspace; architecture control, not an experimental reproduction."
    generic["assumptions"] = ["Two binwise gamma/Poisson background constraints and one shared 3% signal normalization nuisance."]
    generic["likelihood"] = {"workspace": str(rd / "two-bin-workspace.json"), "measurement": "control",
                             "poi_cap": 32, "normalization": {"kind": "signal_strength"}}
    two_bin = run("two-bin", generic)
    command("different-likelihood", "compare-recipes", "--left", counting, "--right", two_bin,
            "--out", rd / "different-likelihood.json", success=False)
    bounded = deepcopy(spec)
    bounded["likelihood"]["poi_cap"] = 10
    run("unresolved-bound", bounded, success=False)
    if args.native_spec:
        native = json.loads(args.native_spec.expanduser().resolve().read_text())
        native["generation"]["events"] = 100
        native["generation"]["seed"] = 1729
        a = run("drell-yan", native)
        bspec = deepcopy(native)
        bspec["generation"]["seed"] = 1730
        b = run("drell-yan-replica", bspec)
        command("same-physics-new-seed", "compare-recipes", "--left", a, "--right", b,
                "--out", rd / "same-physics-new-seed.json")
        c = deepcopy(native)
        c["generation"]["run_settings"]["dynamical_scale_choice"] = 3
        scale = run("different-scale", c)
        command("scale-mismatch", "compare-recipes", "--left", a, "--right", scale,
                "--out", rd / "scale-mismatch.json", success=False)
        mu = deepcopy(native)
        mu["generation"]["process"] = "p p > mu+ mu-"
        mu["generation"]["observable"]["final_state_pdg"] = [-13, 13]
        muon = run("dimuon", mu)
        command("process-mismatch", "compare-recipes", "--left", a, "--right", muon,
                "--out", rd / "process-mismatch.json", success=False)
    # Deliberate output corruption after all good comparisons must invalidate both
    # status and comparison; restore the exact bytes and demonstrate recovery.
    p = counting_b / "outputs/result.json"
    before = p.read_bytes()
    try:
        p.write_bytes(before + b"\n")
        command("tampered-status", "status", "--rundir", counting_b, success=False)
        command("tampered-comparison", "compare-recipes", "--left", counting, "--right", counting_b, success=False)
    finally:
        p.write_bytes(before)
    command("restored-comparison", "compare-recipes", "--left", counting, "--right", counting_b)
    write(rd / "summary.json", {"passed": all(r["passed"] for r in records), "commands": len(records),
        "native_events_requested": 400 if args.native_spec else 0, "workers": 1,
        "approval_mode": "scripted_yes", "expert_review": False,
        "scope": "CLI workflow and recipe controls, not an agent comparison or paper reproduction"})
    print(json.dumps(json.loads((rd / "summary.json").read_text()), indent=2))


if __name__ == "__main__":
    main()
