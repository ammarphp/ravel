#!/usr/bin/env python3
"""preflight_watcher.py -- validate a completion-watcher's FIRE COMMAND before it is armed (N3/G24).
stdlib-only, read-only except the preflight artifact it writes. fail-loud.

Kills the N3 failure: a backgrounded completion-watcher whose fire command is a 3-arg call to a 5-arg
script -- never smoke-tested, it crashes hours later at SCAN-DONE, invisibly. Before arming a watcher,
exercise its fire command: (1) `bash -n` syntax; (2) an arity probe vs the target script's declared
required-positional count. Refuse (nonzero) on failure; write logs/<name>.preflight.json.

Usage:
  preflight_watcher.py --arm --rundir <dir> --name <watcher> --fire "<command>" [--target <script>]
  preflight_watcher.py --assert-all --rundir <dir>       # Stop-branch: every armed watcher preflighted
  preflight_watcher.py --selftest
Exit codes: 0 PASS * 1 domain FAIL (bad fire / missing preflight) * 2 usage/not-a-dir
"""

# Permit direct source execution as well as normal package imports.
if not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
    __package__ = "ravel.workflow"

import argparse, hashlib, json, os, re, shlex, subprocess, sys
from pathlib import Path
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


def _resolve_timestamp():
    return os.environ.get("PREFLIGHT_WATCHER_UTC", "")


def _fingerprint(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update((str(p) + "\x00").encode("utf-8"))
    return h.hexdigest()


def _load_run_state(rundir):
    try:
        with open(os.path.join(rundir, "run_state.json")) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _target_required_arity(target):
    """Number of REQUIRED positional args the target declares (None if undetectable)."""
    if not target or not os.path.isfile(target):
        return None
    if not target.endswith(".py"):
        try:
            txt = open(target, encoding="utf-8", errors="replace").read()
        except OSError:
            return None
        nums = {int(m) for m in re.findall(r"\$\{?([1-9])\b", txt)}
        return max(nums) if nums else None
    try:
        r = subprocess.run([sys.executable, target, "--help"],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return None
    usage = r.stdout or r.stderr or ""
    m = re.search(r"usage:.*(?:\n[ \t]+\S.*)*", usage)   # continuations are indented; stop at blank line
    if not m:
        return None
    line = re.sub(r"\s+", " ", m.group(0))
    line = re.sub(r"\[[^\]]*\]", "", line)               # drop optional groups
    line = re.sub(r"usage:\s*\S+", "", line, count=1)    # drop 'usage: prog'
    return len([t for t in line.split() if re.match(r"^[A-Za-z][\w-]*$", t)])


def _count_positionals(fire, target=None):
    try:
        toks = shlex.split(fire)
    except ValueError:
        return 0
    base = os.path.basename(target) if target else None
    start = None
    for i, t in enumerate(toks):
        if base and os.path.basename(t) == base:
            start = i + 1
            break
    if start is None:
        start = 2 if toks[:1] and toks[0] in ("python", "python3", "bash", "sh") else 1
    return sum(1 for t in toks[start:] if not t.startswith("-"))


def probe_fire_command(fire, target=None):
    checks, ok = [], True
    try:
        r = subprocess.run(["bash", "-n", "-c", fire], capture_output=True, text=True, timeout=20)
        syn_ok, syn_err = (r.returncode == 0), r.stderr.strip()[:200]
    except Exception as e:
        syn_ok, syn_err = False, f"{type(e).__name__}: {e}"[:200]
    checks.append({"name": "bash-n-syntax", "level": "PASS" if syn_ok else "FAIL",
                   "msg": "fire command parses" if syn_ok else f"bash -n rejected it: {syn_err}"})
    ok &= syn_ok
    req = _target_required_arity(target)
    if req is not None:
        prov = _count_positionals(fire, target)
        arity_ok = prov >= req
        checks.append({"name": "arity", "level": "PASS" if arity_ok else "FAIL",
                       "msg": f"fire passes {prov} positional arg(s); target declares {req} required"
                              + ("" if arity_ok else " -- ARITY MISMATCH (N3: e.g. a 3-arg call to a "
                                 "5-arg script)")})
        ok &= arity_ok
    else:
        checks.append({"name": "arity", "level": "INFO",
                       "msg": "no --target / undetectable arity -- syntax-only preflight"})
    return ("pass" if ok else "fail"), checks


def durable_target_errors(rundir, target):
    """A durable watcher target is a regular, nonlinked run member outside transient scratch."""
    from pathlib import Path
    if not target:
        return ['watcher_target_not_durable']
    root = Path(rundir).absolute()
    if ('..' in Path(target).parts
            or any(parent.is_symlink() for parent in (root, *root.parents))):
        return ['watcher_target_not_durable']
    root, path = root.resolve(), Path(target).absolute()
    try:
        relative = path.relative_to(root)
    except ValueError:
        return ['watcher_target_not_durable']
    if (not path.is_file() or any(parent.is_symlink() for parent in (path, *path.parents))
            or any(part in ('scratch', '.work', 'tmp') for part in relative.parts)):
        return ['watcher_target_not_durable']
    return []


def _controller_watcher(rundir):
    try:
        from ravel.controller.store import controller_owned
    except ModuleNotFoundError as exc:
        if exc.name in {'ravel', 'ravel.controller'}:
            return False
        raise
    return controller_owned(__import__('pathlib').Path(rundir)) is not None


def _retained_target(rundir, fire, target):
    """Controller watchers use declared inputs with current, digest-checked custody.

    An accepted custody destination under inputs/ is a controller declaration. A step
    output must additionally be a declared input of the retained plan. Legacy runs keep
    their existing preflight; a damaged controller claim never falls back to that path.
    """
    from ravel.controller.store import controller_owned, store_for
    try:
        root = Path(rundir).resolve()
        if controller_owned(root) is None:
            return None
        store = store_for(root)
        if store.check_binding(root):
            raise ValueError("the controller run binding is not current")
        if not target:
            raise ValueError("the controller watcher names no retained target")
        path = Path(target)
        path = path if path.is_absolute() else root / path
        relative = path.relative_to(root)
        if ".." in relative.parts or not relative.parts or relative.parts[0] not in ("inputs", "steps"):
            raise ValueError("the target is outside durable controller inputs and adopted outputs")
        if any(p.is_symlink() for p in (path, *path.parents) if p == root or root in p.parents):
            raise ValueError("the target has a symbolic link in its custody path")
        if not path.is_file():
            raise ValueError("the retained target is absent")
        lexer = shlex.shlex(fire, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        tokens = list(lexer)
        if not tokens or any(token and all(c in ";&|<>()" for c in token) for token in tokens):
            raise ValueError("the controller fire command must be one retained target invocation")
        executable = os.path.basename(tokens[0])
        if executable in ("python", "python3", "sh", "bash"):
            invoked = tokens[1] if len(tokens) > 1 else None
        else:
            invoked = tokens[0]
        if invoked not in (str(path), relative.as_posix()):
            raise ValueError("the fire command does not name the retained target")
        latest = {}
        for entry in store.scan("custody"):
            row = entry["record"]
            if isinstance(row.get("artifact"), str):
                latest[row["artifact"]] = row
        declared = set()
        plan_record = store.latest("plan")
        if plan_record:
            plan = json.loads(store.get_blob(plan_record["record"]["blob"]))
            declared = {row.get("artifact") for step in plan.get("steps") or ()
                        for row in step.get("inputs") or () if isinstance(row, dict)}
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        retained = any(row.get("status") == "accepted" and row.get("destination") == relative.as_posix()
                       and row.get("sha256") == actual
                       and (relative.parts[0] == "inputs" or artifact in declared)
                       for artifact, row in latest.items())
        if not retained:
            raise ValueError("the target has no current controller-retained input declaration with matching bytes")
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"name": "retained-target", "level": "FAIL", "code": "watcher_target_not_durable",
                "msg": str(exc)[:500]}
    return {"name": "retained-target", "level": "PASS", "msg": "target is a controller-retained declared input"}


def arm_watcher(rundir, name, fire, target):
    # A controller watcher's target must be a durable run member and a current, retained declared input;
    # either refusal is recorded before the target runs.
    durable = durable_target_errors(rundir, target) if _controller_watcher(rundir) else []
    retained = None if durable else _retained_target(rundir, fire, target)
    if durable:
        verdict, checks = probe_fire_command(fire, None)
        verdict = 'fail'
        checks.append({'name': 'durable-target', 'level': 'FAIL', 'code': 'watcher_target_not_durable',
                       'msg': '; '.join(durable)})
    elif retained and retained["level"] == "FAIL":
        verdict, checks = "fail", [retained]
    else:
        verdict, checks = probe_fire_command(fire, target)
        if retained:
            checks.insert(0, retained)
    rec = {"schema_version": 1, "generated_utc": _resolve_timestamp(),
           "generator": "preflight_watcher.py", "generated_by": "preflight_watcher.py --arm",
           "input_fingerprint": _fingerprint(name, fire, target or ""),
           "watcher": name, "fire": fire, "target": target, "checks": checks, "verdict": verdict}
    rec["refusal_codes"] = [c["code"] for c in checks if c.get("code") and c["level"] == "FAIL"]
    dest = os.path.join(rundir, "logs", f"{name}.preflight.json")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w") as f:
        json.dump(rec, f, indent=2)
    return rec, os.path.relpath(dest, rundir)


def assert_all_watchers(rundir):
    st = _load_run_state(rundir)
    problems = []
    for w in (st.get("armed_watchers") or []):
        nm = (w.get("name") if isinstance(w, dict) else None) or "?"
        pf = w.get("preflight") if isinstance(w, dict) else None
        if not pf:
            problems.append(f"armed watcher {nm!r}: no preflight pointer in run_state")
            continue
        p = os.path.join(rundir, pf)
        if not os.path.isfile(p):
            problems.append(f"armed watcher {nm!r}: preflight artifact missing on disk ({pf})")
            continue
        try:
            doc = json.load(open(p))
        except (OSError, json.JSONDecodeError) as e:
            problems.append(f"armed watcher {nm!r}: preflight unreadable ({e})")
            continue
        if doc.get("verdict") != "pass":
            problems.append(f"armed watcher {nm!r}: preflight verdict={doc.get('verdict')!r} (not 'pass')")
    return problems


def _assert_all_main(args):
    if not os.path.isdir(args.rundir or ""):
        print(f"preflight_watcher: not a directory: {args.rundir}", file=sys.stderr)
        return 2
    problems = assert_all_watchers(args.rundir.rstrip("/"))
    if args.json:
        print(json.dumps({"gate": "armed-watcher-preflight", "exit": 1 if problems else 0,
                          "problems": problems}, indent=2))
    else:
        for p in problems:
            print(f"[FAIL] {p}")
        if not problems:
            print("every armed watcher has a passing preflight artifact")
    return 1 if problems else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", action="store_true")
    ap.add_argument("--assert-all", action="store_true")
    ap.add_argument("--rundir")
    ap.add_argument("--name")
    ap.add_argument("--fire")
    ap.add_argument("--target")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.arm:
        if not (args.rundir and args.name and args.fire):
            print("preflight_watcher --arm needs --rundir --name --fire", file=sys.stderr)
            return 2
        if not os.path.isdir(args.rundir):
            print(f"preflight_watcher: not a directory: {args.rundir}", file=sys.stderr)
            return 2
        rec, rel = arm_watcher(args.rundir.rstrip("/"), args.name, args.fire, args.target)
        if args.json:
            print(json.dumps(rec, indent=2))
        else:
            for c in rec["checks"]:
                print(f"[{c['level']}] {c['name']}: {c['msg']}")
            print(f"verdict={rec['verdict']}  wrote {rel}")
        print(f"ARMED: name={args.name} preflight={rel} verdict={rec['verdict']}", file=sys.stderr)
        return 0 if rec["verdict"] == "pass" else 1
    if args.assert_all:
        if not args.rundir:
            print("preflight_watcher --assert-all needs --rundir", file=sys.stderr)
            return 2
        return _assert_all_main(args)
    print(__doc__, file=sys.stderr)
    return 2


def _selftest():
    import tempfile
    fails = []
    with tempfile.TemporaryDirectory(prefix="preflight_selftest_") as td:
        target = os.path.join(td, "wait_and_assemble.py")
        with open(target, "w") as f:
            f.write("#!/usr/bin/env python3\nimport argparse\n"
                    "ap=argparse.ArgumentParser()\n"
                    "for n in ('scandir','manifest','backend','pdf','out'):\n"
                    "    ap.add_argument(n)\n"
                    "ap.parse_args()\n")
        req = _target_required_arity(target)
        ok0 = (req == 5)
        print(f"[selftest] 0 target arity detected (=5): got {req}  {'ok' if ok0 else 'FAIL'}")
        if not ok0: fails.append(f"arity detect got {req}, expected 5")
        v_bad, _ = probe_fire_command(f"python3 {target} a b c", target)
        ok1 = (v_bad == "fail")
        print(f"[selftest] 1 3-arg call to 5-arg target -> fail: {'ok' if ok1 else 'FAIL'}")
        if not ok1: fails.append("arity mismatch not caught")
        v_ok, _ = probe_fire_command(f"python3 {target} a b c d e", target)
        ok2 = (v_ok == "pass")
        print(f"[selftest] 2 5-arg call -> pass: {'ok' if ok2 else 'FAIL'}")
        if not ok2: fails.append("valid arity rejected")
        v_syn, _ = probe_fire_command('python3 "unterminated', None)
        ok3 = (v_syn == "fail")
        print(f"[selftest] 3 bash -n catches broken syntax -> fail: {'ok' if ok3 else 'FAIL'}")
        if not ok3: fails.append("bash -n did not catch syntax error")
        rundir = os.path.join(td, "run"); os.makedirs(rundir)
        rc = main(["--arm", "--rundir", rundir, "--name", "wait_and_assemble",
                   "--fire", f"python3 {target} a b c", "--target", target])
        wrote = os.path.isfile(os.path.join(rundir, "logs", "wait_and_assemble.preflight.json"))
        ok4 = (rc == 1 and wrote)
        print(f"[selftest] 4 --arm bad fire -> exit 1 + preflight.json written: {'ok' if ok4 else 'FAIL'}")
        if not ok4: fails.append(f"--arm bad fire rc={rc} wrote={wrote}")
        good = os.path.join(td, "arun"); os.makedirs(os.path.join(good, "logs"))
        rc_ok = main(["--arm", "--rundir", good, "--name", "wait_and_assemble",
                      "--fire", f"python3 {target} a b c d e", "--target", target])
        with open(os.path.join(good, "run_state.json"), "w") as f:
            json.dump({"armed_watchers": [{"name": "wait_and_assemble",
                      "preflight": "logs/wait_and_assemble.preflight.json"}]}, f)
        probs_ok = assert_all_watchers(good)
        ok5 = (rc_ok == 0 and probs_ok == [])
        print(f"[selftest] 5 assert-all with a passing preflight -> clean: {'ok' if ok5 else 'FAIL'}")
        if not ok5: fails.append(f"assert-all false positive: {probs_ok}")
        with open(os.path.join(good, "run_state.json"), "w") as f:
            json.dump({"armed_watchers": [{"name": "ghost", "preflight": "logs/ghost.preflight.json"}]}, f)
        probs_bad = assert_all_watchers(good)
        ok6 = (len(probs_bad) == 1)
        print(f"[selftest] 6 assert-all with a missing preflight -> 1 problem: {'ok' if ok6 else 'FAIL'}")
        if not ok6: fails.append(f"assert-all missed a missing preflight: {probs_bad}")
    if fails:
        for f in fails:
            print(f"SELFTEST FAIL: {f}", file=sys.stderr)
        return 1
    print("preflight_watcher selftest: PASS (7 case(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
