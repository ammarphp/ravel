"""A small command surface over the existing validation, replay, and audit engines."""
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
        return {"validate": _validate, "replay": _replay, "audit": _audit}[args.command](args)
    except (OSError, ValueError) as exc:
        print(f"ravel: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("ravel: interrupted", file=sys.stderr)
        return 130
