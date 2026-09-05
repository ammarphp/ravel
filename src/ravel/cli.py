"""A small command surface over the existing intake, validation, replay, and audit engines."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from . import __version__, validate_task_contract
from .validation.validate_task_contract import SCHEMA, load_contract
from .evidence_layout import resolve
from .paths import module_command, repository_root
from .resources import payload_files, resource_root


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="ravel", description=__doc__)
    ap.add_argument("--version", action="version", version=f"ravel-hep {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    initiate = sub.add_parser("initiate", help="draft an intake contract and empty run ledger; never runs compute")
    request = initiate.add_mutually_exclusive_group(required=True)
    request.add_argument("--prompt", help="physics request to interpret as a draft")
    request.add_argument("--prompt-file", type=Path, help="UTF-8 file containing the physics request")
    initiate.add_argument("--out", type=Path, required=True,
                          help="new run directory; existing paths are never overwritten")
    initiate.add_argument("--interpretation", type=Path,
                          help="host-agent interpretation JSON with exact request hash and evidence spans")
    status = sub.add_parser("status", help="derive a compact current-state packet from live artifacts")
    status.add_argument("--rundir", type=Path, required=True)
    status.add_argument("--write", action="store_true", help="also refresh current_state.json")
    validate = sub.add_parser("validate", help="validate a task contract; never authorizes compute")
    choice = validate.add_mutually_exclusive_group(required=True)
    choice.add_argument("contract", type=Path, nargs="?", help="task_contract.json")
    choice.add_argument("--schema", action="store_true", help="print the existing validator schema")
    validate.add_argument("--json", action="store_true", help="emit machine-readable validation")
    replay = sub.add_parser("replay", help="re-fit the bundled fast benchmark from cached inputs")
    replay.add_argument("--out", type=Path, default=Path("ravel-replay"),
                        help="new output directory; existing directories are never overwritten")
    audit = sub.add_parser("audit", help="inspect a source checkout with the existing R1-R9 audit")
    audit.add_argument("--root", type=Path, help="Ravel source checkout (otherwise search cwd parents)")
    audit.add_argument("--out", type=Path, help="write the audit report to this explicit path")
    return ap


def _initiate(args) -> int:
    from .workflow import route_prompt, workflow_state

    prompt = (args.prompt if args.prompt is not None else
              args.prompt_file.expanduser().read_bytes().decode("utf-8"))
    if not prompt.strip():
        raise ValueError("the request must not be blank; compute_authorized=false")
    if args.interpretation:
        from .workflow.state_io import read_json
        contract = route_prompt.route(prompt, interpretation=read_json(args.interpretation))
    else:
        contract = route_prompt.route(prompt)
    errors = validate_task_contract(contract)
    if errors:
        print("ravel: invalid draft route; compute_authorized=false:\n" +
              "\n".join(f"  - {error}" for error in errors), file=sys.stderr)
        return 1
    if contract["task_mode"] == "unsupported":
        print("ravel: unsupported request; compute_authorized=false:\n" +
              "\n".join(f"  - {reason}" for reason in contract["blocking"]), file=sys.stderr)
        return 1

    # Do not resolve the final path before mkdir: even a dangling symlink is an
    # existing destination and must not silently redirect a new run elsewhere.
    output = args.out.expanduser().absolute()
    output.mkdir(parents=True, exist_ok=False)
    try:
        inputs = output / "inputs"
        inputs.mkdir()
        contract_path = inputs / "task_contract.json"
        contract_path.write_text(json.dumps(contract, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (output / "request.txt").write_text(prompt, encoding="utf-8")
        # Read the persisted bytes through the same strict reader used by validate.
        persisted = load_contract(contract_path)
        errors = validate_task_contract(persisted)
        if errors:
            raise ValueError("persisted task contract is invalid: " + "; ".join(errors))
        state = workflow_state.new_state(str(output), persisted, str(contract_path), "")
        workflow_state.write_state(str(output), state)
        if contract.get("intake", {}).get("kind") == "method_study":
            intent = contract["intake"]
            (output / "method_proposal.md").write_text(
                "# Draft method study\n\n" + intent["objective"] +
                "\n\nRequested outputs:\n\n" + "\n".join("- " + x for x in intent["requested_outputs"]) +
                "\n\nResolve before designing an execution plan:\n\n" +
                "\n".join("- " + x for x in intent["unresolved"]) +
                "\n\nNo model training, data access, statistical claim, or compute approval is implied.\n",
                encoding="utf-8")
        from .workflow.current_state import write_packet
        write_packet(output)
    except (OSError, ValueError) as exc:
        raise ValueError(f"intake did not complete; partial output retained at {output}; "
                         f"compute_authorized=false: {exc}") from exc

    print(f"Draft intake created: {output}")
    print(f"task_mode={contract['task_mode']} compute_plan={contract['compute_plan']} "
          "compute_authorized=false")
    print("Intake uses a deterministic action parser or a grounded host-agent interpretation. "
          "The contract is a draft; current_state.json records the next required step.")
    print("Next: resolve required inputs and flagged assumptions, then present and obtain approval "
          "for the CHECK-IN 1 plan before generation or scans. No compute was launched.")
    return 0


def _status(args) -> int:
    from .workflow.current_state import build_packet, write_packet
    packet = (write_packet if args.write else build_packet)(args.rundir)
    print(json.dumps(packet, indent=2, allow_nan=False))
    return 0 if packet["execution"]["status"] != "invalid" else 1


def _validate(args) -> int:
    if args.schema:
        print(json.dumps(SCHEMA, indent=2))
        return 0
    try:
        contract = load_contract(args.contract)
    except (OSError, ValueError, UnicodeError, RecursionError) as exc:
        errors = [f"cannot read contract: {exc}"]
        code = 2
    else:
        errors = validate_task_contract(contract)
        code = 1 if errors else 0
    result = {"valid": code == 0, "errors": errors, "compute_authorized": False}
    if args.json:
        print(json.dumps(result, indent=2))
    elif errors:
        print("INVALID task contract:\n" + "\n".join(f"  - {error}" for error in errors))
    else:
        print("Valid task contract. This does not authorize compute or certify a physics result.")
    return code


def _replay(args) -> int:
    # Check before creating output so an incomplete installation leaves no stub directory.
    versions = {}
    for dependency in ("pyhf", "numpy", "scipy", "matplotlib", "iminuit", "PyYAML"):
        try:
            versions[dependency] = importlib.metadata.version(dependency)
        except importlib.metadata.PackageNotFoundError as exc:
            raise ValueError("Replay dependencies are missing. Install 'ravel-hep[replay]' "
                             "or requirements-replay.txt from the checkout.") from exc
    root = resource_root()
    fingerprint = hashlib.sha256()
    for relative in sorted(payload_files(root)):
        fingerprint.update(relative.encode() + b"\0")
        fingerprint.update(hashlib.sha256(resolve(root, relative).read_bytes()).digest())
    for module in sorted(Path(__file__).parent.rglob("*.py")):
        fingerprint.update(str(module.relative_to(Path(__file__).parent)).encode() + b"\0")
        fingerprint.update(hashlib.sha256(module.read_bytes()).digest())
    output = args.out.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = {"ravel_version": __version__, "python": platform.python_version(),
                   "platform": platform.platform(), "packages": versions,
                   "installed_distributions": dict(sorted(
                       (dist.metadata["Name"], dist.version) for dist in importlib.metadata.distributions()
                       if dist.metadata["Name"])),
                   "bundle_sha256": fingerprint.hexdigest(),
                   "generated": datetime.now(timezone.utc).isoformat(),
                   "scope": "fresh statistics and provenance checks; cached event simulation and acceptance certification"}
    (output / "environment.json").write_text(json.dumps(environment, indent=2) + "\n")
    print("Replay uses cached events; acceptance certification may come from the recorded baseline.", flush=True)
    # Interpreter selection avoids silently escaping the lock into a local conda environment.
    return subprocess.call(module_command("ravel.validation.benchmark", "--fast", "--python-current",
                            "--work-dir", str(output / "work"), "--out", str(output / "results.json")))


def _audit(args) -> int:
    candidates = ([args.root.expanduser().resolve()] if args.root else
                  [Path.cwd(), *Path.cwd().parents])
    root = next((candidate for candidate in candidates
                 if (candidate / "scripts/audit.py").is_file()
                 and (candidate / "benchmarks/capabilities.json").is_file()
                 and (candidate / "docs/workflow").is_dir()), None)
    if root is None:
        raise ValueError("The R1-R9 audit needs a Ravel source checkout. Clone "
                         "https://github.com/ammarphp/ravel and run 'ravel audit --root PATH'. "
                         "The wheel contains only the curated replay bundle.")
    cmd = [sys.executable, str(root / "scripts/audit.py")]
    if args.out:
        target = args.out.expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"audit output already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--write", "--out", str(target)])
    print("Audit scores the files available in this checkout; completion is not a physics certification.", flush=True)
    return subprocess.call(cmd, cwd=root)


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try:
        return {"initiate": _initiate, "status": _status, "validate": _validate,
                "replay": _replay, "audit": _audit}[args.command](args)
    except (OSError, ValueError) as exc:
        print(f"ravel: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ravel: interrupted", file=sys.stderr)
        return 130
