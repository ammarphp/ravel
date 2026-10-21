"""`ravel gate`: the host-neutral gate verdict.

A host without hooks asks before acting; a host with hooks runs the same code through a shim.

  ravel gate --rundir <run> --action <gate|tool_call> [--command <text>] [--session ID] --json

`--action` is a decision-gate name or `tool_call`; a tool call's command text is classified
into a gate (`launch` for compute launches, and the R-50 classes) or into `none`, which is
allowed. Exit status: 0 allow, 2 deny, 1 usage error or a missing run for a gated action.
Without `--rundir` the run comes from the R-50 registry (`active_run.resolve`), never the
newest run.

Providers: every gated decision requires decision_gate.check. The launch built-ins
pre_intake and launch_approval additionally retain the pre-release launch checks.
Claude Code's Bash hook delegates to the same verdict as the CLI.
"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shlex
import sys

from . import active_run, host_governance

GATES = ("approve_plan", "launch", "failed_stage_feedback", "checkin2_accept", "correction", "deviation",
         "research_choice", "delivery", "final_task", "report_integrity", "export", "unblind",
         "spend_above_ceiling")
ACTIONS = GATES + ("tool_call",)
WRITE_ACTIONS = ("protected_write", "deviation_check")
DELIVERY_GATES = ("delivery", "final_task", "export")

_PYTHON = re.compile(r"python(?:[0-9]+(?:[.][0-9]+)*)?$")
# gate_wiring subcommands that record operator text or decisions; agents are denied them like approve.
_OPERATOR_WIRING = (["respond"], ["steer"], ["checkin1"])
_COMPUTE_MODULES = ("scan_orchestrator", "scan_babysitter", "stage_supervisor")
_READERS = {"echo", "printf", "cat", "grep", "rg"}
_GENERATORS = re.compile(r"generate_events|mg5_aMC|^mg5$|pythia_shower|run-pipeline-native[.]sh|madevent", re.I)
# Command prefixes that run their argument, with the options of each that take a value.
_PREFIX_WRAPPERS = {"env": ("-u", "--unset", "-C", "--chdir", "-S"), "nohup": (), "setsid": (),
                    "time": ("-f", "-o"), "nice": ("-n", "--adjustment"), "command": (), "exec": ("-a",),
                    "caffeinate": ("-t", "-w"), "stdbuf": ("-i", "-o", "-e"),
                    "conda": ("-n", "--name", "-p", "--prefix", "--cwd")}
_COMPUTE_BODY = r"\bravel[.]workflow[.](?:{0})\b|\bfrom\s+ravel[.]workflow\s+import\b[^;\n]*\b(?:{0})\b"


def _python_body_names(body, names):
    """True when a python -c body imports one of the named ravel.workflow modules."""
    return bool(re.search(_COMPUTE_BODY.format("|".join(names)), body))


def _utc():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(code, gate, provider, message, fix="", pins=()):
    return {"code": code, "gate": gate, "provider": provider, "message": message, "fix": fix,
            "pins": list(pins)}


# --------------------------------------------------------------------------- #
#  Command classification
# --------------------------------------------------------------------------- #

def _segments(command):
    """Split physical shell segments before shlex discards comments and quotes."""
    try:
        for line in (command or "").replace("\\\n", "").splitlines():
            lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
            lexer.whitespace_split = True
            segment = []
            for token in lexer:
                if token and all(ch in ";&|" for ch in token):
                    if segment:
                        yield segment
                    segment = []
                else:
                    segment.append(token)
            if segment:
                yield segment
    except ValueError:
        return  # malformed shell syntax cannot execute


def _argv(segment):
    """Unwrap known launch wrappers; quoted arguments of readers are never commands."""
    args = list(segment)
    while args:
        if re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", args[0]):
            args.pop(0)
            continue
        name = os.path.basename(args[0])
        if name == "command" and args[1:2] in (["-v"], ["-V"]):
            return []  # a lookup, not an execution
        if name == "conda" and args[1:2] == ["run"]:
            args = args[2:]
        elif name in _PREFIX_WRAPPERS:
            args = args[1:]
        else:
            break
        # Drop the wrapper's own options, including the value of an option that takes one.
        while args and args[0].startswith("-") and args[0] != "-":
            flag = args.pop(0)
            if flag in _PREFIX_WRAPPERS.get(name, ()) and args:
                args.pop(0)
    return args


def _segment_gate(segment):
    if "--help" in segment or "-h" in segment:
        return "none"
    argv = _argv(segment)
    if not argv:
        return "none"
    exe = os.path.basename(argv[0])
    if exe in _READERS:
        return "none"
    if exe in ("bash", "sh", "zsh"):
        if "-c" in argv:
            i = argv.index("-c")
            return classify(argv[i + 1]) if len(argv) > i + 1 else "none"
        argv = argv[1:]
        if not argv:
            return "none"
        exe = os.path.basename(argv[0])
    if _PYTHON.fullmatch(exe):
        if "-c" in argv:
            i = argv.index("-c")
            body = argv[i + 1] if len(argv) > i + 1 else ""
            if _python_body_names(body, _COMPUTE_MODULES):
                return "launch"
            return "launch" if _GENERATORS.search(body) else "none"
        if "-m" in argv:
            i = argv.index("-m")
            argv = argv[i + 1:]
        else:
            argv = argv[1:]
            while argv and argv[0].startswith("-"):
                argv.pop(0)
        if not argv:
            return "none"
        exe = os.path.basename(argv[0])
    if exe in ("ravel", "ravel.__main__"):
        sub = argv[1:]
        if sub[:2] == ["scan", "launch"] or sub[:1] == ["run"]:
            return "launch"
        if sub[:1] == ["stage"]:
            return "none" if sub[1:2] in (["list"], ["show"], ["status"]) else "launch"
        if sub[:2] in (["partitions", "run"], ["backend", "launch"]):
            return "launch"
        if sub[:1] == ['steer']:
            return 'none' if sub[1:2] in (['ack'], ['state']) else 'approve_plan'
        if sub[:1] == ['respond']:
            return 'approve_plan'
        if sub[:3] in (['gate-wiring', 'steer', 'ack'], ['gate-wiring', 'steer', 'state']):
            return 'none'
        if sub[:1] == ["gate-wiring"] and sub[1:2] in _OPERATOR_WIRING:
            return "approve_plan"  # the operator's response, steering and CHECK-IN 1 paths
        return {"approve": "approve_plan", "go": "checkin2_accept", "science-correct": "correction",
                "result-pack": "delivery", "export-submission": "export"}.get(sub[0] if sub else "", "none")
    module = argv[0]
    if module in ("ravel.workflow.gate_wiring", "gate_wiring.py") or exe == "gate_wiring.py":
        if argv[1:3] in (['steer', 'ack'], ['steer', 'state']):
            return 'none'
        return "approve_plan" if argv[1:2] in _OPERATOR_WIRING else "none"
    if module in ("ravel.workflow.scan_orchestrator", "scan_orchestrator.py") or exe == "scan_orchestrator.py":
        # As for `ravel scan`: only the launch subcommand launches; plan, status, assemble and rebase read.
        return "launch" if argv[1:2] == ["launch"] else "none"
    if any(module in ("ravel.workflow." + name, name + ".py") or exe == name + ".py"
           for name in _COMPUTE_MODULES):
        return "launch"
    if module == "ravel.workflow.partitioned_execution" and argv[1:2] == ["run"]:
        return "launch"
    if module == "ravel.workflow.execution_backend" and argv[1:2] == ["launch"]:
        return "launch"
    if _GENERATORS.search(exe) or any(arg.endswith(".cmnd") for arg in argv[1:]):
        return "launch"
    if exe in ("workflow_state.py", "ravel.workflow.workflow_state"):
        return {"approve": "approve_plan", "delegated-approve": "approve_plan", "go": "checkin2_accept",
                "delegated-go": "checkin2_accept"}.get(argv[1] if len(argv) > 1 else "", "none")
    return {"result_pack.py": "delivery", "ravel.workflow.result_pack": "delivery",
            "submission_export.py": "export", "ravel.workflow.submission_export": "export"}.get(exe, "none")


def _after_options(args):
    """The script and its arguments, after the interpreter's own leading options (as `_segment_gate` reads them)."""
    args = list(args)
    while args and args[0].startswith("-"):
        args.pop(0)
    return args


def explicit_scan(command):
    """Scan driver argv, including Python/module and shell wrappers."""
    for segment in _segments(command):
        if _segment_gate(segment) != "launch":
            continue
        argv = _argv(segment)
        if not argv:
            continue
        exe = os.path.basename(argv[0])
        if exe in ("bash", "sh", "zsh") and "-c" in argv:
            index = argv.index("-c")
            if len(argv) > index + 1 and explicit_scan(argv[index + 1]):
                return True
            continue
        if _PYTHON.fullmatch(exe):
            if "-c" in argv:
                index = argv.index("-c")
                body = argv[index + 1] if len(argv) > index + 1 else ""
                if _python_body_names(body, ("scan_orchestrator", "scan_babysitter")):
                    return True
                continue
            argv = argv[argv.index("-m") + 1:] if "-m" in argv else _after_options(argv[1:])
        elif exe in ("bash", "sh", "zsh"):
            argv = argv[1:]
        if not argv:
            continue
        exe = os.path.basename(argv[0])
        if exe in ("ravel", "ravel.__main__") and argv[1:3] == ["scan", "launch"]:
            return True
        if argv[0] in ("ravel.workflow.scan_orchestrator", "ravel.workflow.scan_babysitter") or exe in (
                "scan_orchestrator.py", "scan_babysitter.py"):
            return True
    return False


def _babysitter(segment):
    """True when the segment runs the scan babysitter, which launches the scan's points itself."""
    argv = _argv(segment)
    if argv and os.path.basename(argv[0]) in ("bash", "sh", "zsh") and "-c" not in argv:
        argv = argv[1:]
    if argv and _PYTHON.fullmatch(os.path.basename(argv[0])):
        if "-c" in argv:
            index = argv.index("-c")
            return _python_body_names(argv[index + 1] if len(argv) > index + 1 else "", ("scan_babysitter",))
        argv = argv[argv.index("-m") + 1:] if "-m" in argv else _after_options(argv[1:])
    return bool(argv) and (argv[0] == "ravel.workflow.scan_babysitter"
                           or os.path.basename(argv[0]) == "scan_babysitter.py")


def _required_plan(command):
    for segment in _segments(command):
        if _segment_gate(segment) != "launch":
            continue
        argv = _argv(segment)
        if argv and os.path.basename(argv[0]) in ("bash", "sh", "zsh") and "-c" in argv:
            index = argv.index("-c")
            if len(argv) > index + 1 and _required_plan(argv[index + 1]) == "scan":
                return "scan"
        if "--go" in segment and explicit_scan(" ".join(shlex.quote(t) for t in segment)):
            return "scan"
        if _babysitter(segment):
            return "scan"  # it has no --go: every run of it feeds the bulk scan
    return None


def classify(command):
    """The gate a tool call's executable argv acts on, or 'none'."""
    gates = [_segment_gate(segment) for segment in _segments(command)]
    return "launch" if "launch" in gates else next((gate for gate in gates if gate != "none"), "none")


# --------------------------------------------------------------------------- #
#  Pre-execution launch chain (the Claude Code Bash hook runs exactly this)
# --------------------------------------------------------------------------- #

def _route_marker(project, session):
    return Path(project) / "logs" / (".route-pending-" + session) if session else None


def launch_errors(command, *, rundir=None, session_id="", cwd=None, project=None):
    """Messages that refuse a generation launch before it executes; [] allows it.

    (1) not detached (nohup/setsid), (2) not pre-intake (route-pending marker and no run),
    (3) a valid task contract whose compute plan admits generation, (4) a v2 CHECK-IN 1
    approval still binding the current input bytes, (5) the generation recipe exists (D7),
    (6) the launch is supervised (run_stage | stage_supervisor | run-pipeline-native.sh).
    A command that is not a generation launch, or a development session (no run, no marker),
    returns [].
    """
    cmd = command or ""
    scan = explicit_scan(cmd)
    if classify(cmd) != "launch":
        return []
    if re.search(r"\bnohup\b|\bsetsid\b|start_new_session", cmd):
        return ["DETACHED generation launch -- nohup/setsid silently defeats the completion "
                "notification (N6). Use the harness run_in_background with stage_supervisor/run_stage."]
    project = Path(project) if project is not None else host_governance.project_root()
    rd = Path(rundir) if rundir is not None else active_run.resolve(session_id, cwd, project)
    if rd is None:
        marker = _route_marker(project, session_id)
        if marker is not None and marker.is_file():
            return ["generation BEFORE intake -- this session has no run/contract yet. "
                    "Fire physicist-intake first (docs/workflow/start.md)."]
        return []
    if (rd / "inputs/science.json").is_file():
        # The science envelope owns the task, budget and bound input bytes. Its
        # supervised stage path does not have a native generation task contract.
        approval_errors = _approval_errors(rd, _required_plan(cmd))
        if approval_errors:
            return ["UNAPPROVED or invalid approval: " + "; ".join(approval_errors)]
        if not re.search(r"run_stage|stage_supervisor|\bravel\s+(?:stage|run)\b", cmd):
            return ["UNSUPERVISED science launch -- use the approved supervised science stage path."]
        return []
    try:
        from ravel.validation import validate_task_contract as contract_validator
    except Exception as e:
        return ["task-contract validator is unavailable: " + str(e)]
    contract = None
    for rel in ("inputs/task_contract.json", "task_contract.json"):
        fp = rd / rel
        if fp.is_file():
            try:
                contract = contract_validator.load_contract(str(fp))
            except Exception as e:
                return ["invalid task_contract.json: " + str(e)]
            break
    contract_errors = contract_validator.validate(contract)
    if contract_errors:
        return ["invalid task_contract.json: " + "; ".join(contract_errors)]
    plan = contract["compute_plan"]
    if plan not in ("smoke", "full", "scan"):
        return ["generation is outside task_contract compute_plan=" + plan]
    approval_errors = _approval_errors(rd, _required_plan(cmd))
    if approval_errors:
        return ["UNAPPROVED or invalid approval: " + "; ".join(approval_errors)]
    try:
        from . import resource_census
        rcode = resource_census.assert_pre_generate(str(rd))[0]
    except Exception:
        rcode = 0
    if rcode != 0:
        return ["NO generation recipe recorded for the declared model (D7) -- fetch/record it "
                "(resource_census.py --debug recipe-search -> inputs/generation_recipe.json) BEFORE "
                "generating; recipe-after-generation is how the trial hung."]
    if not scan and not re.search(r"run_stage|stage_supervisor|run-pipeline-native\.sh|\bravel\s+stage\b", cmd):
        return ["UNSUPERVISED generation launch -- wrap it (stage_supervisor.py / run_stage / "
                "run-pipeline-native.sh) so a hang converts to a completion (the trial hung silent, D6)."]
    return []


# --------------------------------------------------------------------------- #
#  The verdict
# --------------------------------------------------------------------------- #

def _decision_gate():
    try:
        return importlib.import_module("ravel.workflow.decision_gate")
    except ImportError:
        return None


def _provider_rows(gate, external):
    rows = list(external.providers(gate)) if external is not None else [{"id": "decision_gate", "active": False}]
    if gate == "launch":
        rows += [{"id": name, "active": True} for name in ("pre_intake", "launch_approval")]
    return rows


def _approval_errors(rd, required_plan):
    """Use each run kind's byte-bound approval verifier; never relabel machine approval."""
    try:
        if (Path(rd) / "inputs/science.json").is_file():
            from . import science
            return science.verify_approval_envelope(rd)
        from . import workflow_state
        return workflow_state.verify_approval(str(rd), required_plan=required_plan)
    except Exception as exc:
        return ["approval verifier is unavailable or failed: " + str(exc)]


def _builtin_errors(rd, gate, command, session_id, cwd, project, providers):
    if gate != "launch":
        return []
    if command is not None and classify(command) == "launch":
        messages = launch_errors(command, rundir=rd, session_id=session_id, cwd=cwd, project=project)
    else:
        messages = _approval_errors(rd, _required_plan(command))
    return [_error("launch_approval", gate, "launch_approval", message,
                   "record CHECK-IN 1 approval for the run kind, then use supervised execution") for message in messages]


def verdict(rundir, action, command=None, *, session_id=None, cwd=None, project=None, floor=None):
    """The gate verdict object (also printed by `ravel gate --json`)."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; expected one of {', '.join(ACTIONS + WRITE_ACTIONS)}")
    if floor is not None and floor not in ("R0", "R1", "R2", "R3"):
        raise ValueError("floor must be R0|R1|R2|R3")
    session_id = session_id if session_id is not None else active_run.session_from_env()
    project = Path(project) if project is not None else host_governance.project_root(rundir)
    cwd = cwd if cwd is not None else os.getcwd()
    gate = classify(command) if action == "tool_call" else action
    rd = Path(rundir).expanduser().absolute() if rundir is not None else active_run.resolve(session_id, cwd, project)
    result = {"schema_version": 1, "kind": "gate-verdict",
              "rundir": str(rd) if rd is not None else None,
              "run_id": rd.name if rd is not None else None,
              "session_id": session_id or None, "action": action, "gate": gate,
              "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest() if command is not None else None,
              "decision": "allow", "errors": [], "providers": [],
              "pre_execution_guards": host_governance.pre_execution_guards(project),
              "enforcement_surface_sha256": host_governance.enforcement_surface_sha256(project),
              "checked_utc": _utc()}
    if gate == "none":
        return result
    external = _decision_gate()
    try:
        providers = _provider_rows(gate, external)
    except Exception as exc:
        providers = [{"id": "decision_gate", "active": False, "reason": str(exc)}]
    result["providers"] = providers
    if rd is None:
        if gate == "launch" and classify(command) == "launch":
            result["errors"] = [_error("pre_intake", gate, "pre_intake",
                "generation BEFORE intake -- this session has no registered run/contract yet.",
                "fire physicist-intake first (docs/workflow/start.md)")]
        else:
            result["errors"] = [_error("no_active_run", gate, "host_gate",
                "no run is registered for this session or working directory",
                "pass --rundir, or create the run with `ravel initiate`")]
        if external is None:
            result["errors"].append(_error("provider_inactive", gate, "decision_gate",
                "required provider decision_gate is inactive", "install the decision-gate module"))
        result["decision"] = "deny"
        return result
    if not rd.is_dir():
        result["errors"] = [_error("no_active_run", gate, "host_gate", f"run directory does not exist: {rd}",
                                   "pass an existing --rundir")]
        if external is None:
            result["errors"].append(_error("provider_inactive", gate, "decision_gate",
                "required provider decision_gate is inactive", "install the decision-gate module"))
        result["decision"] = "deny"
        return result
    errors = []
    if external is None:
        errors.append(_error("provider_inactive", gate, "decision_gate",
                             "required provider decision_gate is inactive", "install the decision-gate module"))
    if external is not None:
        action_record = {"kind": action, "digest": result["command_sha256"], "summary": (command or "")[:200],
                         "pins": [], "node_id": None, "scope": None}
        if floor is not None:
            action_record["floor"] = floor
        try:
            errors += [host_governance._as_dict(e) for e in external.check(rd, gate, action_record)]
        except Exception as exc:
            # A decision that raised is a refusal; a validator missing from the install is named as one.
            errors.append(_decision_failure(gate, exc))
    errors += _builtin_errors(rd, gate, command, session_id, cwd, project, providers)
    result["providers"] = providers
    result["errors"] = errors
    result["decision"] = "deny" if errors else "allow"
    return result


def exit_code(result):
    if any(e.get("code") == "no_active_run" for e in result["errors"]):
        return 1
    return 2 if result["decision"] == "deny" else 0


def hook_bash(raw, project):
    """PreToolUse-on-Bash shim: 'allow' or 'block:<reason>' for the Claude Code hook."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return "allow"
    if (data.get("tool_name") or "") != "Bash":
        return "allow"
    cmd = ((data.get("tool_input") or {}).get("command") or "")
    result = verdict(None, "tool_call", cmd, session_id=data.get("session_id") or "",
                     cwd=data.get("cwd") or "", project=project)
    return "block:" + result["errors"][0]["message"] if result["decision"] == "deny" else "allow"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ravel gate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rundir", type=Path, help="the run (default: the session's registered run)")
    ap.add_argument("--action", help="a decision-gate name or tool_call")
    ap.add_argument("--command", help="the exact command text of a tool call")
    ap.add_argument("--session", help="host session id (default: RAVEL_SESSION_ID or the host's variable)")
    ap.add_argument("--project", type=Path, help="project whose hook table governs the run")
    ap.add_argument("--path", type=Path, help="write destination for protected_write or deviation_check")
    ap.add_argument("--host", default="codex", choices=("claude", "codex", "gemini", "opencode", "antigravity"))
    ap.add_argument("--floor", choices=("R0", "R1", "R2", "R3"), help="raise the decision risk floor")
    ap.add_argument("--json", action="store_true", help="print the verdict object")
    ap.add_argument("--hook", choices=("bash",), help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.hook == "bash":
        project = args.project or host_governance.project_root()
        print(hook_bash(sys.stdin.read(), project))
        return 0
    # Every explicit gate call notices switched-off or redirected hooks (detection, never a block).
    host_governance.observe_host(args.project, source="gate", rundir=args.rundir)
    if args.action not in ACTIONS + WRITE_ACTIONS:
        ap.print_usage(sys.stderr)
        print(f"ravel gate: --action must be one of {', '.join(ACTIONS + WRITE_ACTIONS)}", file=sys.stderr)
        return 1
    if args.action in ('protected_write', 'deviation_check'):
        if args.path is None:
            ap.error('--path is required for write checks')
        from . import host_guards
        project = args.project or host_governance.project_root(args.rundir)
        data = {'tool_name': 'Write', 'tool_input': {'file_path': str(args.path)},
                'session_id': args.session or active_run.session_from_env(), 'cwd': str(args.rundir or Path.cwd())}
        try:
            errors = host_guards.write_errors(data, project, deviations=args.action == 'deviation_check')
        except Exception as exc:
            errors = ['write guard unavailable: ' + str(exc)]
        result = {'decision': 'deny' if errors else 'allow', 'errors': errors, 'action': args.action}
        print(json.dumps(result) if args.json else result['decision'] + ': ' + '; '.join(errors))
        return 2 if errors else 0
    if args.action == "tool_call" and args.command is None:
        print("ravel gate: --action tool_call requires --command", file=sys.stderr)
        return 1
    try:
        result = verdict(args.rundir, args.action, args.command, session_id=args.session,
                         project=args.project, floor=args.floor)
    except (OSError, ValueError) as exc:
        print(f"ravel gate: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{result['decision']}: gate={result['gate']} run={result['run_id'] or '-'}")
        for error in result["errors"]:
            print(f"  - [{error['provider']}] {error['message']}\n    fix: {error['fix']}")
    return exit_code(result)


def _decision_failure(gate, exc):
    """The typed refusal for a decision gate that raised: a validator absent from the install, else the failure."""
    missing = exc.name if isinstance(exc, ModuleNotFoundError) else None
    if isinstance(missing, str) and missing.startswith("ravel.validation."):
        return _error("validator_unavailable", gate, "decision_gate",
                      f"{missing.rsplit('.', 1)[-1]} validator is unavailable: {exc}",
                      "restore the installed RAVEL validation package from your own terminal")
    return _error("decision_gate_failed", gate, "decision_gate", str(exc),
                  "repair the decision-gate records named in the message")


if __name__ == "__main__":
    sys.exit(main())
