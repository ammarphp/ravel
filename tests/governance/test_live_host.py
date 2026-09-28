"""Real-host (live) campaigns (smoke spec §9 steps 1-7): the pinned host, the approval checks and the single-use
approval ledger, the never-present names and the model byte check; the live builder, the real-host launch policy, the
per-launch proxy with host attribution, the credential exception on the recording launcher with the post-run sweep,
redaction and keychain check, the runner's live path (preflight, the credential pause, limit, the stop rules, signal
handling, the core limit), the host probes and the live checks.

Every approval, token, model id and binary here is SYNTHETIC: the "Claude Code CLI" is tests/governance/live_mock.py
(or tests/governance/mock_claude_cli.py for the rehearsal), every credential is a dummy in a scratch directory and the
keychain lookup is a synthetic script. No test calls or reads a real host, a real credential or a real keychain, and
every signal a test sends goes to a process it started, by exact pid.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from governance import allowlist_proxy, canonical, cli, contracts, credentials, isolation, live, runner
from governance.canonical import ContractError

ARMS = list(contracts.ARMS)
SPEC = {"tasks": [{"id": "lf-b"}, {"id": "lf-d"}], "seeds": [11]}


@pytest.fixture(scope="module", autouse=True)
def ledger_home(tmp_path_factory):
    """Every approval ledger of this module lives in a scratch directory, never the user's (live.LEDGER_DIR, E-77):
    module-scoped and autouse, so it is in place before any module fixture builds a campaign. Its parent is laid out as
    the procedure leaves ~/.local/share/ravel-eval (smoke-request S3's `mkdir -p`: the umask's 0755, with the pinned
    copy's hosts/ in it); the ledger's own directory is created 0700 by the first claim (E-89)."""
    parent = Path(os.path.realpath(tmp_path_factory.mktemp("ledger"))) / "ravel-eval"
    (parent / "hosts").mkdir(parents=True)
    parent.chmod(0o755)
    home = parent / "approvals"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(live, "LEDGER_DIR", str(home))
        yield home
BUDGET = {"usd_per_run": 2.0, "seconds_per_run": 900.0, "max_broker_ops": 40, "max_fits": 4, "global_usd_cap": 16.0,
          "global_seconds_cap": 7680.0}
SHA = hashlib.sha256(b"synthetic claude binary").hexdigest()


def pin(**changes):
    fields = {"adapter": "claude_cli",
              "executable": "/synthetic-pins/claude-code-2.1.281/claude.app/Contents/MacOS/claude",
              "executable_sha256": SHA, "version": "2.1.281", "model": "claude-synthetic-5", "effort": "high"}
    return live.HostPin(**{**fields, **changes})


def approval(**changes):
    record = {"schema_version": 2, "kind": "synthetic_engineering_smoke",
              "approved_by": "SYNTHETIC approver (budget owner, PKT-D07)", "approved_utc": "2026-09-26T12:00:00Z",
              "authorization_text": "SYNTHETIC authorization for a unit test.",
              "scope": {"tasks": ["lf-b", "lf-d"], "seeds": [11], "arms": ARMS, "assignments": 8,
                        "host": pin().fields()},
              "caps": {"usd_per_run": 2.0, "seconds_per_run": 900.0, "runs": 8, "global_usd_cap": 16.0,
                       "global_seconds_cap": 7680.0},
              "spend_envelope": contracts.SMOKE_SPEND_ENVELOPE,
              "credential": {"kind": "claude_subscription_oauth_setup_token", "env_name": "CLAUDE_CODE_OAUTH_TOKEN",
                             "revoke_after_smoke": True},
              "account_preconditions": {"usage_credits_or_extra_usage": "off", "managed_policy": "none",
                                        "shared_quota_accepted": True},
              "decisions": {"subprocess_env_scrub_off": "E-SYN-1", "multiprocessing_unavailable": "E-SYN-2"},
              "human_reviews": "deferred", "retry_policy": "none", "single_use": True}
    for path, value in changes.items():
        target = record
        *parents, last = path.split(".")
        for key in parents:
            target = target[key]
        target[last] = value
    return record


def problems(record, *, spec=SPEC, host=None, budget=BUDGET, arms=ARMS, ledger=()):
    return live.approval_problems(record, spec=spec, host=host or pin().fields(), budget=budget, arms=arms,
                                  ledger=list(ledger))


def test_a_matching_approval_has_no_problems():
    assert problems(approval()) == []


@pytest.mark.parametrize("change, match", [
    ({"caps.usd_per_run": 2}, "caps.usd_per_run 2 differs"),           # 2 is not 2.0: canonical bytes
    ({"caps.usd_per_run": 1.0, "caps.global_usd_cap": 8.0}, "caps.usd_per_run"),
    ({"caps.global_seconds_cap": 7200.0}, "caps.global_seconds_cap"),
    ({"caps.seconds_per_run": 600.0}, "caps.seconds_per_run"),
    ({"scope.tasks": ["lf-b"], "scope.assignments": 4, "caps.runs": 4}, "scope.tasks"),
    ({"scope.seeds": [12]}, "scope.seeds"),
    ({"scope.arms": ARMS[:2], "scope.assignments": 4, "caps.runs": 4}, "scope.arms"),
    ({"scope.host.model": "claude-synthetic-6"}, "scope.host.model"),
    ({"scope.host.effort": "medium"}, "scope.host.effort"),
    ({"scope.host.executable_sha256": "0" * 64}, "scope.host.executable_sha256"),
    ({"scope.host.version": "2.1.233"}, "scope.host.version"),
    ({"authorization_text": ""}, "authorization_text"),
    ({"decisions": {"subprocess_env_scrub_off": "E-SYN-1"}}, "missing fields"),
    ({"account_preconditions": {"managed_policy": "none", "shared_quota_accepted": True}}, "missing fields"),
    ({"account_preconditions.shared_quota_accepted": False}, "shared subscription quota"),
    ({"synthetic_extra": True}, "unknown fields"),
])
def test_an_approval_that_differs_is_refused(change, match):
    found = problems(approval(**change))
    assert found and any(match in p for p in found), found


def test_an_approval_already_in_the_ledger_is_refused():
    record = approval()
    entry = {"approval_sha256": live.approval_digest(record), "campaign_id": "smoke-earlier",
             "created_utc": "2026-09-26T12:00:00Z"}
    assert any("single-use" in p for p in problems(record, ledger=[entry]))
    reformatted = json.loads(json.dumps(record, indent=4, sort_keys=False))   # other bytes, same approval
    assert live.approval_digest(reformatted) == entry["approval_sha256"]


def ledger_lines(store):
    """The ledger's lines read without its lock (for assertions made while a claim holds it)."""
    data = (store / live.APPROVAL_LEDGER).read_bytes()
    return [json.loads(line) for line in data.splitlines()]


def test_the_ledger_claims_an_approval_once(tmp_path):
    record = approval()
    sha = live.approval_digest(record)
    assert live.read_approval_ledger(tmp_path) == []
    with live.claim_approval(tmp_path, approval_sha256=sha, campaign_id="smoke-a",
                             created_utc="2026-09-26T12:00:00Z") as entry:
        assert ledger_lines(tmp_path) == [entry]     # written before the body runs
        with pytest.raises(ContractError, match="locked by another build"):   # a claim is exclusive
            live.read_approval_ledger(tmp_path, wait_s=0.2)
    assert [e["campaign_id"] for e in live.read_approval_ledger(tmp_path)] == ["smoke-a"]
    with pytest.raises(ContractError, match="already used by campaign 'smoke-a'"):
        with live.claim_approval(tmp_path, approval_sha256=sha, campaign_id="smoke-b",
                                 created_utc="2026-09-26T13:00:00Z"):
            pytest.fail("a used approval was claimed again")
    assert any("single-use" in p for p in problems(record, ledger=live.read_approval_ledger(tmp_path)))


def test_a_failed_build_leaves_no_ledger_line(tmp_path):
    first = {"approval_sha256": "a" * 64, "campaign_id": "smoke-a", "created_utc": "2026-09-26T12:00:00Z"}
    with live.claim_approval(tmp_path, **first):
        pass
    before = (tmp_path / live.APPROVAL_LEDGER).read_bytes()
    with pytest.raises(RuntimeError, match="SYNTHETIC rename failure"):
        with live.claim_approval(tmp_path, approval_sha256="b" * 64, campaign_id="smoke-b",
                                 created_utc="2026-09-26T13:00:00Z"):
            assert len(ledger_lines(tmp_path)) == 2
            raise RuntimeError("SYNTHETIC rename failure")
    assert (tmp_path / live.APPROVAL_LEDGER).read_bytes() == before
    with live.claim_approval(tmp_path, approval_sha256="b" * 64, campaign_id="smoke-b",
                             created_utc="2026-09-26T13:00:00Z"):
        pass   # the approval was not consumed by the failed build
    assert [e["campaign_id"] for e in live.read_approval_ledger(tmp_path)] == ["smoke-a", "smoke-b"]


def test_a_torn_or_foreign_ledger_fails_closed(tmp_path):
    path = tmp_path / live.APPROVAL_LEDGER
    path.write_bytes(b'{"approval_sha256":"' + b"a" * 64 + b'","campaign_id":"x","created_utc":"2026-09-26T12:00:00Z"}')
    path.chmod(0o600)
    with pytest.raises(ContractError, match="torn"):
        live.read_approval_ledger(tmp_path)
    with pytest.raises(ContractError, match="torn"):
        with live.claim_approval(tmp_path, approval_sha256="b" * 64, campaign_id="y",
                                 created_utc="2026-09-26T12:00:00Z"):
            pass
    path.write_bytes(b'{"approval_sha256":"short"}\n')
    with pytest.raises(ContractError, match="line 1"):
        live.read_approval_ledger(tmp_path)
    path.chmod(0o644)                                   # readable by others: refused whatever it holds
    with pytest.raises(ContractError, match="mode 0600"):
        live.read_approval_ledger(tmp_path)
    path.chmod(0o600)
    path.unlink()
    os.symlink(tmp_path / "elsewhere", path)
    with pytest.raises(OSError):
        live.read_approval_ledger(tmp_path)


def test_concurrent_claims_of_one_approval_admit_exactly_one(tmp_path):
    outcomes, barrier = [], threading.Barrier(4)

    def claim(i):
        barrier.wait()
        try:
            with live.claim_approval(tmp_path, approval_sha256="c" * 64, campaign_id=f"smoke-{i}",
                                     created_utc="2026-09-26T12:00:00Z"):
                outcomes.append("claimed")
        except ContractError:
            outcomes.append("refused")

    threads = [threading.Thread(target=claim, args=(i,)) for i in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(outcomes) == ["claimed", "refused", "refused", "refused"]
    assert len(live.read_approval_ledger(tmp_path)) == 1


def test_the_pinned_binary_must_hold_the_model_id(tmp_path):
    binary = tmp_path / "claude"
    filler = os.urandom(1 << 16)
    binary.write_bytes(filler + b'var catalog=[{id:"claude-synthetic-5",family:"x"}];' + filler)
    assert live.model_in_binary(binary, "claude-synthetic-5")
    assert not live.model_in_binary(binary, "claude-synthetic-6")
    assert not live.model_in_binary(binary, "claude-synthetic")      # a quoted literal, never a prefix
    split = tmp_path / "split"
    split.write_bytes(b"x" * (live.SCAN_BLOCK - 5) + b"'claude-synthetic-5'" + b"y")   # across a block boundary
    assert live.model_in_binary(split, "claude-synthetic-5")
    for bad in ("", "claude synthetic", 'claude"5', "claude-é"):
        with pytest.raises(ContractError):
            live.model_in_binary(binary, bad)


def test_the_host_pin_is_a_full_model_id_and_a_known_effort():
    assert pin().fields() == approval()["scope"]["host"]
    for change in ({"model": "claude-synthetic-5[1m]"}, {"model": " claude"}, {"effort": "extreme"},
                   {"executable": "relative/claude"}, {"executable_sha256": "x"}, {"adapter": "fake"},
                   {"version": ""}):
        with pytest.raises(ContractError):
            pin(**change)


def test_never_present_names():
    names = ["PATH", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
             "CLAUDE_CODE_SIMPLE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE", "CLAUDE_SECURESTORAGE_CONFIG_DIR",
             "CLAUDE_CODE_REMOTE_SESSION_ID", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST",
             "CLAUDE_CODE_CUSTOM_OAUTH_URL", "CLAUDE_CODE_OAUTH_CLIENT_ID", "NODE_OPTIONS", "BUN_INSTALL",
             "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "HTTPS_PROXY"]
    assert live.never_present(names) == sorted(set(names) - {"PATH", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR",
                                                             "HTTPS_PROXY"})
    assert live.CREDENTIAL_ENV_NAMES == {"claude_cli": {"CLAUDE_CODE_OAUTH_TOKEN": "none"}}


def test_an_approval_naming_another_credential_variable_is_refused():
    found = problems(approval(**{"credential.env_name": "ANTHROPIC_AUTH_TOKEN"}))
    assert any("credential variable" in p for p in found)


def test_approval_problems_never_mutate_their_inputs():
    record, spec, budget = approval(), copy.deepcopy(SPEC), dict(BUDGET)
    frozen = canonical.canonical_bytes([record, spec, budget])
    problems(record, spec=spec, budget=budget)
    assert canonical.canonical_bytes([record, spec, budget]) == frozen


# ================================================================ the live path (smoke spec §9 steps 5-7)

HERE = Path(__file__).resolve().parent
PYTHON = os.path.realpath(getattr(sys, "_base_executable", sys.executable))
PREFIX = os.path.realpath(sys.base_prefix)
SANDBOXED = isolation.sandbox_available() and isolation.census_available() and PYTHON.startswith(PREFIX + "/")
needs_sandbox = pytest.mark.skipif(not SANDBOXED, reason="Seatbelt and its census are required (macOS)")
MOCK_MODEL, MOCK_VERSION, CREATED = "claude-synthetic-5", "2.1.281", "2026-09-26T12:00:00Z"
LIVE_BUDGET = {"usd_per_run": 2.0, "seconds_per_run": 900.0, "global_seconds_cap": 7680.0}
RATES = {MOCK_MODEL: {"input_tokens": 2.0, "output_tokens": 10.0, "cache_creation_input_tokens": 2.5,
                      "cache_read_input_tokens": 0.2}}


def render(source, path, **replace):
    """Write a SYNTHETIC mock host with this interpreter's shebang (-I) and read-only mode."""
    body = source.read_text().split("\n", 1)[1]
    for key, value in replace.items():
        body = body.replace(key, value)
    path.write_text(f"#!{PYTHON} -I\n" + body)
    path.chmod(0o555)


# A SYNTHETIC `security`, run as `python -I -c SECURITY_MOCK <args>` (so it runs inside the sandbox too, where a script
# outside the profile's read roots could not even be executed): a lookup answers "not found" (44); show-keychain-info
# of a named keychain opens that file, which succeeds unsandboxed (0) and is denied under a profile that denies it
# (161, security's own code for a UNIX EPERM), as the real one behaves for the login keychain.
SECURITY_MOCK = r"""
import sys
args = sys.argv[1:]
if args[:1] == ["find-generic-password"]:
    sys.exit(44)
if args[:1] == ["show-keychain-info"] and len(args) > 1:
    try:
        open(args[1], "rb").close()
    except PermissionError:
        sys.exit(161)
    except OSError:
        sys.exit(206)
    sys.exit(0)
sys.exit(37)
"""
# A SYNTHETIC `codesign` (display only), run as `python -I -c CODESIGN_MOCK <args>`: the CodeDirectory line on stderr
# for `-d --verbose=2`, the entitlements plist on stdout for `-d --entitlements - --xml`. __FLAGS__ and __EXTRA__ are
# replaced per test: the default is a hardened runtime without get-task-allow, as the real 2.1.281 pin reads (F1).
CODESIGN_MOCK = r"""
import sys
args = sys.argv[1:]
if "--entitlements" in args:
    sys.stdout.write('<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                     '<key>com.apple.security.cs.allow-jit</key><true/>__EXTRA__</dict></plist>')
    sys.exit(0)
sys.stderr.write("Executable=" + args[-1] + "\nCodeDirectory v=20500 size=1 flags=__FLAGS__ hashes=1+0\n")
sys.exit(0)
"""


def codesign_stand_in(flags="0x10000(runtime)", extra=""):
    return (PYTHON, "-I", "-c", CODESIGN_MOCK.replace("__FLAGS__", flags).replace("__EXTRA__", extra))


class Lab:
    """A SYNTHETIC live lab: a store, a parent for the roots, a harness-owned read-only pin directory holding the mock
    CLI, a dummy credential (0600 in a 0700 directory), a synthetic login keychain file in that denied directory and a
    synthetic `security` (SECURITY_MOCK)."""

    def __init__(self, base: Path):
        self.base = base
        self.store, self.roots = base / "store", base / "roots"
        self.roots.mkdir()
        self.pins = base / "pins"
        self.pins.mkdir()
        self.exe = self.pins / "claude"
        render(HERE / "live_mock.py", self.exe, __MOCK_VERSION__=MOCK_VERSION)
        self.pins.chmod(0o555)
        self.sha = canonical.sha256_file(self.exe)
        self.cred_dir = base / "cred"
        self.cred_dir.mkdir(mode=0o700)
        self.cred = self.cred_dir / "token"
        self.token = "sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16)
        self.cred.write_text(self.token + "\n")
        self.cred.chmod(0o600)
        self.security = (PYTHON, "-I", "-c", SECURITY_MOCK)
        self.codesign = codesign_stand_in()
        self.keychain = self.cred_dir / "login.keychain-db"   # SYNTHETIC: under a deny root, never a real keychain
        self.keychain.write_text("SYNTHETIC keychain file\n")

    def pin(self, **changes):
        fields = {"adapter": "claude_cli", "executable": str(self.exe), "executable_sha256": self.sha,
                  "version": MOCK_VERSION, "model": MOCK_MODEL, "effort": "high"}
        return live.HostPin(**{**fields, **changes})

    def approval(self, **changes):
        record = approval(**changes)
        record["scope"]["host"] = {**self.pin().fields(), **{k.split(".")[-1]: v for k, v in changes.items()
                                                               if k.startswith("scope.host.")}}
        return record

    def cleanup(self):
        self.pins.chmod(0o755)


@pytest.fixture(scope="module")
def lab(tmp_path_factory):
    made = Lab(Path(os.path.realpath(tmp_path_factory.mktemp("lab"))))
    yield made
    made.cleanup()


def live_session(patch, lab):
    """The coordinator environment of a SYNTHETIC live run in this test process: the live flag, none of the names that
    may never reach a real host, the synthetic keychain lookup, the denial collector off (log show is slow and
    best effort), and the two host-wide preflight facts this process cannot provide (a hard core limit of 0 would be
    irreversible here; the host's System V objects belong to other programs) replaced."""
    patch.setenv("RAVEL_EVAL_LIVE", "1")
    for name in live.never_present(os.environ) + ["CLAUDE_CODE_OAUTH_TOKEN"]:
        patch.delenv(name, raising=False)
    patch.setattr(live, "SECURITY_COMMAND", lab.security)
    patch.setattr(live, "CODESIGN_COMMAND", lab.codesign)
    patch.setattr(live, "login_keychain", lambda: str(lab.keychain))
    patch.setattr(live, "sandbox_denials", lambda start, end, **kw: {
        "available": False, "count": None, "truncated": False, "error": "SYNTHETIC: not collected in tests"})
    patch.setattr(runner, "core_limit_problem", lambda: None)
    patch.setattr(live, "user_sysv_objects", lambda: [])


def build_live(lab, campaign_id, *, approval_record=None, tasks=("lf-b", "lf-d"), budget=None, pin=None,
               credential_file=None, **kw):
    record = approval_record if approval_record is not None else lab.approval()
    data = record if isinstance(record, bytes) else json.dumps(record, indent=1).encode()
    return live.build_live_campaign(
        lab.store, campaign_id=campaign_id, created_utc=CREATED, seeds=[11], schedule_seed=7,
        subjects_root=lab.roots / f"{campaign_id}-s", host_state_root=str(lab.roots / f"{campaign_id}-h"),
        tasks=list(tasks), pin=pin or lab.pin(), credential_file=credential_file or str(lab.cred),
        approval_bytes=data, budget=dict(budget or LIVE_BUDGET), **kw)


def write_probe_record(campaign, *, drop=(), fail=(), pricing=True, hp07=None):
    """A SYNTHETIC passing host-probe record (the probes' own tests run them; a runner test needs only the gate).
    ``hp07``: HP-07's detail (default: made after the lab's credential file was minted)."""
    probes = [{"id": f"HP-{i:02d}", "required": i not in (10, 11, 12), "ok": f"HP-{i:02d}" not in fail,
               "detail": {"SYNTHETIC": "test fixture"}} for i in range(1, 14) if f"HP-{i:02d}" not in drop]
    for probe in probes:
        if probe["id"] == "HP-13":
            probe["detail"] = {"pricing_eligible": pricing, "cli_price_per_mtok": RATES}
        if probe["id"] == "HP-07":   # the lab's credential file exists: a record made after it was minted
            probe["detail"] = hp07 or {"directory_present": True, "file_present": True,
                                       "stat": {"directory": live.EPERM, "credential": live.EPERM}}
    parent = campaign / "coordinator" / live.HOST_PROBE_DIR
    parent.mkdir(exist_ok=True)
    n = 1 + max([int(p.name) for p in parent.iterdir() if p.name.isdigit()] or [0])
    (parent / str(n)).mkdir()
    record = {"schema_version": 1, "probe_run": n, "SYNTHETIC": True, "ok": not fail, "unclean_launches": [],
              "probes": probes}
    canonical.write_once(parent / str(n) / "result.json", runner._pretty(record))
    return record


def plant(patch, modes):
    """SYNTHETIC: the mock CLI reads its mode from inputs/mock-mode.txt in the runs named in ``modes``."""
    original = runner._subject_files
    patch.setattr(runner, "_subject_files", lambda c, r: {**original(c, r), "inputs/mock-mode.txt":
                                                          modes[r["run_id"]].encode()} if r["run_id"] in modes
                  else original(c, r))


def gate_passes(patch):
    """SYNTHETIC: the behavioral gate is taken as passed, and so is the S10a review of run 1 (their own tests run the
    real checks; scenario tests need only launches)."""
    patch.setattr(runner, "behavioral_record", lambda *a, **k: (None, "0" * 64))
    patch.setattr(live, "go_no_go_problem", lambda *a, **k: None)


def runs_of(campaign):
    return canonical.strict_load(campaign / "registry.json")["runs"]


def journal_of(campaign, rid):
    return runner.read_journal(campaign / "runs" / rid / "journal.jsonl")


def closing(campaign, rid):
    return next(r for r in reversed(journal_of(campaign, rid)) if r["state"] in ("exited", "interrupted_crash",
                                                                               "not_started"))


def sealed_json(campaign, rid, name):
    return canonical.strict_load(campaign / "runs" / rid / "sealed" / name)


def all_variants(token):
    return [form for forms in credentials.variants(token.encode()).values() for form in forms]


def files_holding(roots, token):
    """Every regular file under ``roots`` holding the token or any encoded variant (a test-side walk, independent
    of the harness's sweep)."""
    forms, found = all_variants(token), []
    for root in roots:
        for current, _, names in os.walk(root):
            for name in names:
                path = Path(current) / name
                if path.is_symlink() or not path.is_file():
                    continue
                data = path.read_bytes()
                if any(form in data for form in forms) or any(form in name.encode() for form in forms):
                    found.append(str(path))
    return found


# ---------------------------------------------------------------- WI-4: the proxy's host attribution

class Echo:
    """A SYNTHETIC TCP echo on 127.0.0.1 (a thread of this process)."""

    def __init__(self):
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(8)
        self.port = self.server.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            with conn:
                data = conn.recv(1024)
                if data:
                    conn.sendall(data)

    def close(self):
        self.server.close()


def connect_via(port, target, payload=b""):
    with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        sock.sendall(f"CONNECT {target} HTTP/1.1\r\n\r\n".encode())
        status = sock.recv(128).split(b"\r\n")[0].decode()
        echoed = b""
        if " 200 " in status + " " and payload:
            sock.sendall(payload)
            echoed = sock.recv(128)
    return status, echoed


@pytest.mark.skipif(sys.platform != "darwin", reason="proc_pidfdinfo is macOS")
def test_socket_ownership_is_read_from_the_owners_descriptors():
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    port = server.getsockname()[1]
    try:
        with socket.create_connection(("127.0.0.1", port)) as mine:
            local = mine.getsockname()[1]
            assert live.socket_owned_by(os.getpid(), local, port) is True
            assert live.socket_owned_by(os.getpid(), local, port + 1) is False
            child = subprocess.Popen([sys.executable, "-c", f"import socket,time; s=socket.create_connection("
                                      f"('127.0.0.1',{port})); print(s.getsockname()[1], flush=True); time.sleep(5)"],
                                     stdout=subprocess.PIPE, text=True)
            try:
                theirs = int(child.stdout.readline())
                assert live.socket_owned_by(child.pid, theirs, port) is True
                assert live.socket_owned_by(os.getpid(), theirs, port) is False     # a client of another process
                assert live.socket_owned_by(child.pid, local, port) is False
            finally:
                child.kill()   # this test's own child, by its exact pid (Popen handle)
                child.wait()
    finally:
        server.close()
    assert live.socket_owned_by(None, 1, 2) is None and live.socket_owned_by(0, 1, 2) is None


@pytest.mark.skipif(sys.platform != "darwin", reason="proc_pidfdinfo is macOS")
def test_a_non_leader_client_is_denied_by_the_proxy(tmp_path):
    """The task's required proxy test: with attribution, only the owner process's connection is served; another
    process's CONNECT to the same allowlisted target gets 403 and is logged subject_client (attribution other)."""
    echo = Echo()
    proxy = allowlist_proxy.AllowlistProxy([f"127.0.0.1:{echo.port}"], log_path=tmp_path / "proxy.jsonl")
    proxy.owner_check = lambda address: live.socket_owned_by(proxy.owner_pid, address[1], proxy.port)
    proxy.start()
    try:
        proxy.owner_pid = os.getpid()   # this test process is the "leader"
        assert connect_via(proxy.port, f"127.0.0.1:{echo.port}", b"ping") == ("HTTP/1.1 200 Connection Established",
                                                                              b"ping")
        child = subprocess.run([sys.executable, "-c", (
            "import socket; s = socket.create_connection(('127.0.0.1', %d), timeout=10); "
            "s.sendall(b'CONNECT 127.0.0.1:%d HTTP/1.1\\r\\n\\r\\n'); print(s.recv(128).split(b'\\r\\n')[0].decode())"
        ) % (proxy.port, echo.port)], capture_output=True, text=True, timeout=30)
        assert child.stdout.strip() == "HTTP/1.1 403 Forbidden"
        assert connect_via(proxy.port, "api.example.invalid:443")[0] == "HTTP/1.1 403 Forbidden"
    finally:
        proxy.stop()
        echo.close()
    decisions = [(d["decision"], d["reason"], d["attribution"]) for d in proxy.decisions]
    assert decisions == [("allow", "allowlisted", "owner"), ("deny", "subject_client", "other"),
                         ("deny", "not_allowlisted", "owner")]
    assert canonical.read_jsonl(tmp_path / "proxy.jsonl")[0] == proxy.decisions
    summary = runner.proxy_summary(proxy.decisions)
    assert runner.proxy_flags(summary) == ({"proxy_denied_connect"}, {"subject_network_attempt"})


def test_connections_before_the_owner_pid_is_known_are_denied(tmp_path):
    echo = Echo()
    proxy = allowlist_proxy.AllowlistProxy([f"127.0.0.1:{echo.port}"], log_path=tmp_path / "proxy.jsonl")
    proxy.owner_check = lambda address: live.socket_owned_by(proxy.owner_pid, address[1], proxy.port)
    with proxy:
        assert proxy.owner_pid is None
        assert connect_via(proxy.port, f"127.0.0.1:{echo.port}", b"x")[0] == "HTTP/1.1 403 Forbidden"
    echo.close()
    assert [(d["reason"], d["attribution"]) for d in proxy.decisions] == [("owner_unknown", "unknown")]
    assert runner.proxy_flags(runner.proxy_summary(proxy.decisions))[0] == {"proxy_owner_unknown"}


def test_owner_lookup_failure_denies_and_stops(tmp_path, monkeypatch):
    echo = Echo()
    monkeypatch.setattr(live, "socket_owned_by", lambda pid, local, remote: None)   # SYNTHETIC lookup failure
    proxy = allowlist_proxy.AllowlistProxy([f"127.0.0.1:{echo.port}"], log_path=tmp_path / "proxy.jsonl")
    proxy.owner_check = lambda address: live.socket_owned_by(os.getpid(), address[1], proxy.port)
    with proxy:
        assert connect_via(proxy.port, f"127.0.0.1:{echo.port}")[0] == "HTTP/1.1 403 Forbidden"
    echo.close()
    flags, _ = runner.proxy_flags(runner.proxy_summary(proxy.decisions))
    assert flags == {"proxy_owner_unknown"}
    assert live.stop_reason({"flags": sorted(flags)}, [])["rule"] == "S3"

    def raising(address):
        raise OSError("SYNTHETIC lookup error")
    proxy = allowlist_proxy.AllowlistProxy(["127.0.0.1:9"], log_path=tmp_path / "second.jsonl", owner_check=raising)
    with proxy:
        assert connect_via(proxy.port, "127.0.0.1:9")[0] == "HTTP/1.1 403 Forbidden"
    assert proxy.decisions[0]["reason"] == "owner_unknown"


def test_stop_joins_handlers_before_the_log_is_sealed(tmp_path):
    """stop() closes an open tunnel and a connection still sending its request, joins every handler, and only then
    returns: the log is complete, and nothing is written after it (a late decision is counted, never logged)."""
    echo = Echo()
    proxy = allowlist_proxy.AllowlistProxy([f"127.0.0.1:{echo.port}"], log_path=tmp_path / "proxy.jsonl")
    proxy.start()
    tunnel = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)
    tunnel.sendall(f"CONNECT 127.0.0.1:{echo.port} HTTP/1.1\r\n\r\n".encode())
    assert tunnel.recv(128).startswith(b"HTTP/1.1 200")
    idle = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)   # never sends its request line
    time.sleep(0.2)
    started = time.monotonic()
    proxy.stop(join_timeout=10)
    assert time.monotonic() - started < 9
    assert proxy.stop_error is None
    assert not [t for t in threading.enumerate() if t.name.startswith("allowlist-proxy")]
    logged = canonical.read_jsonl(tmp_path / "proxy.jsonl")[0]
    assert logged == proxy.decisions and [d["decision"] for d in logged][0] == "allow"
    proxy._record(("127.0.0.1", 1), "CONNECT late", None, "deny", "not_connect")
    assert proxy.late_decisions == 1 and canonical.read_jsonl(tmp_path / "proxy.jsonl")[0] == logged
    assert "proxy_stop_failed" in runner.proxy_flags(runner.proxy_summary(proxy.decisions, late=1))[0]
    for sock in (tunnel, idle):
        sock.close()
    echo.close()


def test_stop_never_waits_out_a_request_line_timeout(tmp_path):
    """stop() shuts every socket down and lets each handler close its own. Closing a socket right after its shutdown,
    while its handler already waits for a request line, left that read blocked until its 10 s timeout on macOS (about
    one stop in six before the fix, 2026-09-26): stop() stalled and could report a live handler (proxy_stop_failed)."""
    echo = Echo()
    try:
        for i in range(20):
            proxy = allowlist_proxy.AllowlistProxy([f"127.0.0.1:{echo.port}"], log_path=tmp_path / f"proxy-{i}.jsonl")
            proxy.start()
            idle = socket.create_connection(("127.0.0.1", proxy.port), timeout=10)   # never sends its request line
            time.sleep(0.05)
            started = time.monotonic()
            proxy.stop(join_timeout=10)
            elapsed = time.monotonic() - started
            idle.close()
            assert elapsed < 3 and proxy.stop_error is None, (i, elapsed, proxy.stop_error)
            assert not [t for t in threading.enumerate() if t.name.startswith("allowlist-proxy")]
    finally:
        echo.close()


def test_a_proxy_without_attribution_logs_exactly_as_before(tmp_path):
    proxy = allowlist_proxy.AllowlistProxy(["127.0.0.1:9"], log_path=tmp_path / "proxy.jsonl")
    with proxy:
        connect_via(proxy.port, "api.example.invalid:443")
    assert set(proxy.decisions[0]) == {"time_utc", "client", "request", "target", "decision", "reason", "seq"}


# ---------------------------------------------------------------- WI-1: build-live

@pytest.fixture(scope="module")
def built(lab):
    """One SYNTHETIC live campaign (2 tasks x 1 seed x 4 arms) with its behavioral check and a synthetic probe
    record; runs launch in the tests that use it."""
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        campaign = build_live(lab, "smoke-built")
        assert runner.behavioral_check(campaign)["ok"] is True
    write_probe_record(campaign)
    return campaign


@needs_sandbox
def test_build_live_writes_the_claude_host_identity_budget_and_approval(lab, built):
    manifest = canonical.strict_load(built / "campaign.json")
    registry = canonical.strict_load(built / "registry.json")
    host, spec = manifest["host"], registry["spec"]
    assert (host["adapter"], host["executable"], host["executable_sha256"], host["version"], host["model"]) == (
        "claude_cli", str(lab.exe), lab.sha, MOCK_VERSION, MOCK_MODEL)
    assert host["reasoning"] == "--effort high" and host["unknown_fields"] == ["sampling"]
    assert host["network"] == "allowlist_proxy" and host["sandbox"] == "seatbelt"
    assert host["cost_source"] == "host_reported" and host["tool_allowlist"] == ["Bash", "Read", "Write", "Edit"]
    assert (spec["model"], spec["runtime"]) == (f"synthetic {MOCK_MODEL}", f"synthetic claude_cli {MOCK_VERSION}")
    assert manifest["budget"] == {"usd_per_run": 2.0, "seconds_per_run": 900.0, "max_broker_ops": 40, "max_fits": 4,
                                  "max_stage_executions": 6, "global_usd_cap": 16.0, "global_seconds_cap": 7680.0}
    assert len(registry["runs"]) == 8 and [t["id"] for t in spec["tasks"]] == ["lf-b", "lf-d"]
    frozen = (built / "approval_record").read_bytes()
    assert manifest["authorization"]["kind"] == "synthetic_engineering"
    assert manifest["authorization"]["reference_sha256"] == canonical.sha256_bytes(frozen)
    assert json.loads(frozen) == lab.approval()
    ledger = live.read_approval_ledger()
    assert {"approval_sha256": live.approval_digest(lab.approval()), "campaign_id": "smoke-built",
            "created_utc": CREATED} in ledger
    config = canonical.strict_load(built / "coordinator" / "config.json")
    contracts.validate_host_launch(config["host_launch"])
    assert config["host_launch"]["binary_access"] == {"read_literals": [str(lab.exe)], "read_roots": []}
    assert config["host_launch"]["credential"] == {"env_name": "CLAUDE_CODE_OAUTH_TOKEN", "file": str(lab.cred),
                                                   "expected_api_key_source": "none"}
    assert str(lab.cred_dir) in config["forbidden_roots"] and str(lab.cred_dir) in config["host_launch"]["deny_roots"]
    environment = canonical.strict_load(built / "coordinator" / "environment.json")
    assert environment["host_launch"] == config["host_launch"]
    binding = canonical.strict_load(built / "coordinator" / runner.HOST_BINDING)
    assert binding["usd_ceiling"] == 2.0 and runner.PLACEHOLDER_SESSION in binding["argv"]
    assert binding["argv"][binding["argv"].index("--effort") + 1] == "high"
    assert binding["extra_env"]["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] == "0"
    assert binding["extra_env"]["CLAUDE_CODE_CERT_STORE"] == "bundled"
    for root in (lab.roots / "smoke-built-s", lab.roots / "smoke-built-h"):
        assert runner.host_root_problem(root) is None
    assert "credential" not in json.dumps(binding).lower().replace("credentials", "")


@needs_sandbox
def test_build_live_keeps_the_whole_family_and_binds_its_index(built):
    index = canonical.strict_load(built / "coordinator" / "family" / "index.json")
    # the frozen bank holds every registered family (WP12 plan step 7); a live campaign schedules only the runnable
    assert [t["task_id"] for t in index["tasks"] if t["family"] == "likelihood_freshness"] == ["lf-a", "lf-b", "lf-c",
                                                                                           "lf-d"]
    assert index["runnable_families"] == ["likelihood_freshness", "poi_domain_limit", "limit_summary", "yield_normalization", "sample_census"]   # every family since WP12 plan steps 8-9
    environment = canonical.strict_load(built / "coordinator" / "environment.json")
    assert environment["family_index_sha256"] == canonical.sha256_file(built / "coordinator" / "family" / "index.json")
    from governance import campaign_manifest
    assert campaign_manifest.verify(built) == {"ok": True, "errors": []}


def test_build_live_refuses_without_the_live_flag(lab, monkeypatch):
    monkeypatch.delenv("RAVEL_EVAL_LIVE", raising=False)
    with pytest.raises(ContractError, match="RAVEL_EVAL_LIVE=1"):
        build_live(lab, "smoke-unflagged")
    assert not (lab.store / "synthetic" / "smoke-unflagged").exists()
    assert cli.main(["build-live", "--store", str(lab.store), "--campaign-id", "x", "--created-utc", CREATED,
                     "--subjects-root", "/x", "--host-state-root", "/y", "--executable", str(lab.exe),
                     "--executable-sha256", lab.sha, "--host-version", MOCK_VERSION, "--model", MOCK_MODEL,
                     "--effort", "high", "--credential-file", str(lab.cred), "--approval-file", "/nonexistent",
                     "--seed", "11", "--schedule-seed", "7", "--task", "lf-b", "--usd-per-run", "2",
                     "--seconds-per-run", "900", "--global-seconds-cap", "7680"]) == 2


def nothing_left(lab, campaign_id, before):
    assert not (lab.store / "synthetic" / campaign_id).exists()
    assert live.read_approval_ledger() == before
    assert not (lab.roots / f"{campaign_id}-s").exists() and not (lab.roots / f"{campaign_id}-h").exists()


@needs_sandbox
@pytest.mark.parametrize("change, match", [
    ({"caps.usd_per_run": 1.0, "caps.global_usd_cap": 8.0}, "caps.usd_per_run"),
    ({"scope.host.model": "claude-synthetic-6"}, "scope.host.model"),
    ({"scope.host.effort": "medium"}, "scope.host.effort"),
    ({"scope.seeds": [12]}, "scope.seeds"),
    ({"synthetic_extra": True}, "unknown fields"),
    ({"authorization_text": ""}, "authorization_text"),
])
def test_build_live_refuses_an_approval_that_differs(lab, monkeypatch, change, match):
    live_session(monkeypatch, lab)
    before = live.read_approval_ledger()
    with pytest.raises(ContractError, match=match):
        build_live(lab, "smoke-refused", approval_record=lab.approval(**change))
    nothing_left(lab, "smoke-refused", before)


@needs_sandbox
@pytest.mark.parametrize("sample", ["dy-1729", "dy-1730-content-truncated"])
def test_build_live_of_likelihood_tasks_depends_on_the_pinned_lhe_samples(lab, monkeypatch, sample):
    """Review of 2026-09-27 (E-152): every campaign build freezes the whole task bank (E-136), so even a live build of
    likelihood_freshness tasks only reads the pinned LHE samples, none of them under tests/; a missing or changed one
    stops the build before anything is written or the approval is consumed."""
    from governance.tasks import builder
    assert all(not pin["path"].startswith("tests/") for pin in builder.SAMPLES.values())
    live_session(monkeypatch, lab)
    before = live.read_approval_ledger()
    monkeypatch.setitem(builder.SAMPLES, sample, {**builder.SAMPLES[sample], "path": "benchmarks/nonexistent.lhe.gz"})
    with pytest.raises(ContractError, match=f"{sample}: the pinned file benchmarks/nonexistent.lhe.gz cannot be read"):
        build_live(lab, "smoke-no-sample")
    nothing_left(lab, "smoke-no-sample", before)


@needs_sandbox
def test_build_live_refuses_a_reused_approval(lab, built, monkeypatch):
    live_session(monkeypatch, lab)
    before = live.read_approval_ledger()
    with pytest.raises(ContractError, match="single-use"):
        build_live(lab, "smoke-again")       # the approval smoke-built consumed
    nothing_left(lab, "smoke-again", before)


@needs_sandbox
def test_build_live_refuses_a_model_absent_from_the_pinned_binary(lab, monkeypatch):
    live_session(monkeypatch, lab)
    before = live.read_approval_ledger()
    with pytest.raises(ContractError, match="does not appear in the pinned binary"):
        build_live(lab, "smoke-nomodel", pin=lab.pin(model="claude-synthetic-6"),
                   approval_record=lab.approval(**{"scope.host.model": "claude-synthetic-6"}))
    nothing_left(lab, "smoke-nomodel", before)


@needs_sandbox
def test_build_live_orders_tasks_by_the_family_index(lab, monkeypatch):
    live_session(monkeypatch, lab)
    record = lab.approval(**{"approved_utc": "2026-09-26T13:00:00Z"})   # another approval (another digest)
    campaign = build_live(lab, "smoke-order", approval_record=record, tasks=("lf-d", "lf-b"))
    assert [t["id"] for t in canonical.strict_load(campaign / "registry.json")["spec"]["tasks"]] == ["lf-b", "lf-d"]
    with pytest.raises(ContractError, match="not tasks of the family index"):
        build_live(lab, "smoke-unknown-task", approval_record=lab.approval(**{"approved_utc": "2026-09-26T14:00:00Z"}),
                   tasks=("lf-b", "lf-z"))


def test_a_real_host_campaign_refuses_none_test_only(lab):
    with pytest.raises(ContractError, match="only under the Seatbelt sandbox"):
        runner._build_campaign(lab.store, campaign_id="smoke-unsandboxed", created_utc=CREATED, seeds=[11],
                               schedule_seed=7, subjects_root=lab.roots / "u-s", tasks=None, sandbox="none_test_only",
                               budget=None, make_host=None, authorization={}, approval_record=None,
                               host_launch={"SYNTHETIC": True}, source=None, extra_forbidden_roots=(),
                               pin=lab.pin(), approval={"SYNTHETIC": True})


def test_host_roots_are_created_exclusively_or_verified(tmp_path):
    base = Path(os.path.realpath(tmp_path))
    fresh = base / "fresh"
    assert runner.prepare_host_root(fresh, "root") is True and stat.S_IMODE(fresh.stat().st_mode) == 0o700
    assert runner.prepare_host_root(fresh, "root") is False            # an existing private root is verified
    loose = base / "loose"
    loose.mkdir(mode=0o755)
    loose.chmod(0o755)
    with pytest.raises(ContractError, match="mode 0755"):
        runner.prepare_host_root(loose, "root")
    link = base / "link"
    link.symlink_to(fresh)
    with pytest.raises(ContractError, match="symlink"):
        runner.prepare_host_root(link, "root")
    root_owned = next(p for p in ("/var/empty", "/usr") if os.path.isdir(p) and os.lstat(p).st_uid == 0)   # macOS, Linux
    assert "not this user" in runner.host_root_problem(root_owned)   # a directory another user (root) owns
    with pytest.raises(ContractError, match="its parent must exist"):
        runner.prepare_host_root(base / "missing" / "root", "root")


@needs_sandbox
def test_build_live_refuses_a_pinned_binary_path_naming_an_arm(lab, monkeypatch, tmp_path):
    live_session(monkeypatch, lab)
    base = Path(os.path.realpath(tmp_path))
    pins = base / "enforcement-pins"
    pins.mkdir()
    exe = pins / "claude"
    render(HERE / "live_mock.py", exe, __MOCK_VERSION__=MOCK_VERSION)
    pins.chmod(0o555)
    try:
        pin = lab.pin(executable=str(exe), executable_sha256=canonical.sha256_file(exe))
        with pytest.raises(ContractError, match="names"):
            build_live(lab, "smoke-armpin", pin=pin, approval_record=lab.approval(**{
                "scope.host.executable_sha256": pin.executable_sha256}))
    finally:
        pins.chmod(0o755)


@needs_sandbox
def test_a_writable_or_symlinked_pin_is_refused(lab, monkeypatch, tmp_path):
    live_session(monkeypatch, lab)
    base = Path(os.path.realpath(tmp_path))
    writable = base / "pinned"
    writable.mkdir()
    exe = writable / "claude"
    render(HERE / "live_mock.py", exe, __MOCK_VERSION__=MOCK_VERSION)   # the directory keeps its write bits
    pin = lab.pin(executable=str(exe), executable_sha256=canonical.sha256_file(exe))
    with pytest.raises(ContractError, match="without write bits"):
        build_live(lab, "smoke-writable", pin=pin, approval_record=lab.approval(**{
            "scope.host.executable_sha256": pin.executable_sha256}))
    link = base / "claude-link"
    link.symlink_to(lab.exe)
    with pytest.raises(ContractError, match="resolves to"):
        build_live(lab, "smoke-linked", pin=lab.pin(executable=str(link)))


# ---------------------------------------------------------------- WI-3: the real-host launch policy

def test_real_host_policy_adds_exactly_the_binary_state_dirs_proxy_port_denials_and_removes_two_mach_services(lab):
    ws, state = lab.roots / "ws0", lab.roots / "state0"
    host_launch = live.default_host_launch(host_state_root=str(lab.roots / "hosts"), credential_file=str(lab.cred),
                                           pin=lab.pin())
    fake = runner.launch_policy(workspace=ws, subject_prefix=PREFIX, forbidden=[str(lab.store)], port=1)
    real = runner.launch_policy(workspace=ws, subject_prefix=PREFIX, forbidden=[str(lab.store)], port=1,
                                extra_ports=[2], host_access=runner.host_access(host_launch, state))
    assert set(real.read_roots) == set(fake.read_roots)
    assert set(real.read_literals) - set(fake.read_literals) == {str(lab.exe)}
    assert set(real.write_roots) - set(fake.write_roots) == {str(state / "config"), str(state / "tmp")}
    assert real.localhost_ports == (1, 2) and fake.localhost_ports == (1,)
    home = os.path.realpath(os.path.expanduser("~"))
    assert set(real.deny_roots) == {str(lab.cred_dir), os.path.join(home, "Library", "Keychains"),
                                    os.path.join(home, ".claude.json")}
    assert real.mach_services_removed == ("com.apple.SecurityServer", "com.apple.securityd.xpc")
    fake_profile, real_profile = isolation.seatbelt_profile(fake), isolation.seatbelt_profile(real)
    assert "com.apple.trustd.agent" in real_profile and "com.apple.SecurityServer" not in real_profile
    assert "com.apple.securityd.xpc" not in real_profile and "com.apple.SecurityServer" in fake_profile
    added = set(real_profile.splitlines()) - set(fake_profile.splitlines())
    assert added, "the real host adds rules"
    for line in added:   # nothing added grants /private/tmp, the user temp tree, ~/Library, the CLI's own install
        for absent in ('(subpath "/private/tmp")', '(subpath "/private/var/folders")',
                       f'(subpath "{home}/Library")', ".local/share/claude", "pseudo-tty", "ipc-posix"):
            assert not (line.startswith("(allow") and absent in line), (absent, line)


def test_fake_host_profile_is_unchanged():
    """The fake host's policy through the new launch_policy is the policy the old signature built (same profile
    bytes): no host access, one port."""
    ws = Path("/private/var/empty/synthetic-ws")
    old = isolation.SandboxPolicy(read_roots=[ws, PREFIX], write_roots=[ws / "output", ws / "tmp", ws / "home"],
                                  network="localhost", localhost_ports=[7], forbidden_roots=["/private/var/empty/store"])
    new = runner.launch_policy(workspace=ws, subject_prefix=PREFIX, forbidden=["/private/var/empty/store"], port=7)
    assert isolation.seatbelt_profile(new) == isolation.seatbelt_profile(old)


# The fake host's profile bytes for one fixed policy, rendered with 7bad716's isolation.py (the branch point) and
# with the default forbidden roots fixed, so the digest depends on neither the checkout location nor the home: any
# change to what the fake host's profile allows or denies changes it (the test above only compares two renderings of
# the same current code).
FAKE_PROFILE_SHA256_AT_7BAD716 = "78be0863d65de2f110dab5d5523e1a19f68d92cd1de79a7acf52e9e119c2945a"


def test_fake_host_profile_bytes_are_those_of_the_branch_point(monkeypatch):
    monkeypatch.setattr(isolation, "default_forbidden_roots",
                        lambda: ["/synthetic/home/.claude", "/synthetic/home/.codex"])
    ws = Path("/private/var/empty/synthetic-ws")
    policy = runner.launch_policy(workspace=ws, subject_prefix="/synthetic/python-prefix",
                                  forbidden=["/private/var/empty/store"], port=7)
    profile = isolation.seatbelt_profile(policy)
    assert hashlib.sha256(profile.encode()).hexdigest() == FAKE_PROFILE_SHA256_AT_7BAD716, profile


def sandboxed(profile, argv, cwd):
    return subprocess.run([isolation.SANDBOX_EXEC, "-p", profile, *argv], cwd=cwd, env={}, capture_output=True,
                          text=True, timeout=60)


@needs_sandbox
def test_real_host_profile_denies_the_credential_directory_keychains_and_claude_json(tmp_path):
    base = Path(os.path.realpath(tmp_path))
    cred_dir, keychains, claude_json = base / "cred", base / "Keychains", base / ".claude.json"
    for directory in (cred_dir, keychains):
        directory.mkdir()
    for path in (cred_dir / "token", keychains / "login.keychain-db", claude_json):
        path.write_text("SYNTHETIC\n")
    ws, state = base / "ws", base / "state"
    (ws / "output").mkdir(parents=True)
    access = {"read_literals": [], "read_roots": [str(base)], "write_roots": [state / "config", state / "tmp"],
              "deny_roots": [str(cred_dir), str(keychains), str(claude_json)], "mach_services_removed": []}
    profile = isolation.seatbelt_profile(runner.launch_policy(workspace=ws, subject_prefix=PREFIX, forbidden=[],
                                                              port=1, host_access=access))
    code = ("import os, sys\nfor p in sys.argv[1:]:\n    try:\n        os.stat(p); print('stat')\n"
            "    except OSError as e:\n        print(e.errno)\n")
    (base / "readable.txt").write_text("SYNTHETIC\n")
    done = sandboxed(profile, [PYTHON, "-I", "-c", code, str(cred_dir / "token"), str(keychains / "login.keychain-db"),
                               str(claude_json), str(base / "readable.txt")], ws)
    assert done.stdout.split() == ["1", "1", "1", "stat"], done.stdout + done.stderr


@needs_sandbox
def test_real_host_profile_denies_siblings_of_the_pinned_binary_and_writes_outside_its_run_state(tmp_path):
    base = Path(os.path.realpath(tmp_path))
    pins = base / "pins"
    pins.mkdir()
    exe, sibling = pins / "claude", pins / "sibling.txt"
    exe.write_text("#!/bin/sh\necho SYNTHETIC-PIN-RAN\n")
    exe.chmod(0o555)
    sibling.write_text("SYNTHETIC sibling\n")
    ws, state, outside = base / "ws", base / "state", base / "state-sibling"
    for directory in (ws / "output", ws / "tmp", ws / "home", state / "config", state / "tmp", outside):
        directory.mkdir(parents=True)
    access = {"read_literals": [str(exe)], "read_roots": [], "write_roots": [state / "config", state / "tmp"],
              "deny_roots": [], "mach_services_removed": list(contracts.KEYCHAIN_MACH_SERVICES)}
    profile = isolation.seatbelt_profile(runner.launch_policy(workspace=ws, subject_prefix=PREFIX, forbidden=[],
                                                              port=1, host_access=access))
    assert sandboxed(profile, [str(exe)], ws).stdout.strip() == "SYNTHETIC-PIN-RAN"
    code = ("import sys\ndef w(p):\n    try:\n        open(p, 'w').write('x'); return 'ok'\n"
            "    except OSError as e:\n        return str(e.errno)\ndef r(p):\n    try:\n        open(p).read(); return 'ok'\n"
            "    except OSError as e:\n        return str(e.errno)\n"
            "print(r(sys.argv[1]), w(sys.argv[2]), w(sys.argv[3]), w(sys.argv[4]), w(sys.argv[5]))\n")
    done = sandboxed(profile, [PYTHON, "-I", "-c", code, str(sibling), str(state / "config" / "a"),
                               str(state / "tmp" / "b"), str(state / "c"), str(outside / "d")], ws)
    assert done.stdout.split() == ["1", "ok", "ok", "1", "1"], done.stdout + done.stderr


# ---------------------------------------------------------------- WI-2: factory, CLI refusals, the credential pause

def test_claude_factory_builds_the_bound_adapter_from_the_opaque_handle_without_the_arm(lab):
    host_launch = live.default_host_launch(host_state_root=str(lab.roots / "hosts"), credential_file=str(lab.cred),
                                           pin=lab.pin())
    host = live.claude_host_config(lab.pin(), environment_sha256="0" * 64, tools=host_launch["claude"]["tools"])
    campaign = SimpleNamespace(host=host, config={"host_launch": host_launch},
                               budget={"usd_per_run": 2.0, "seconds_per_run": 900.0})
    state, launcher = lab.roots / "hosts" / "0123456789abcdef", object()
    adapter = live.claude_factory(campaign)({"run_id": "r", "task_id": "lf-b", "seed": 11, "behavior": None,
                                             "python": PYTHON, "launcher": launcher, "host_state_dir": str(state)})
    assert adapter.launcher is launcher and adapter.config_dir == state / "config" and adapter.tmp_dir == state / "tmp"
    assert (adapter.effort, adapter.max_budget_usd, adapter.subprocess_env_scrub) == ("high", 2.0, False)
    assert adapter.expected_api_key_source == "none" and adapter.tools == ["Bash", "Read", "Write", "Edit"]
    binding, problems = runner.host_binding(adapter, host, campaign.budget, "synthetic")
    assert problems == []
    placeholder = live.claude_adapter(host, host_launch, campaign.budget, lab.roots / "hosts" / "x", launcher=None)
    assert runner.host_binding(placeholder, host, campaign.budget, "synthetic")[0] == binding   # state-independent


@needs_sandbox
def test_cli_run_refuses_a_live_host_without_the_flag_or_a_passing_preflight(lab, built, monkeypatch, capsys):
    monkeypatch.setattr(cli, "install_live_handlers", lambda: None)   # never alter this test process's rlimits
    monkeypatch.delenv("RAVEL_EVAL_LIVE", raising=False)
    assert cli.main(["run", "--campaign", str(built)]) == 2
    assert "RAVEL_EVAL_LIVE=1" in json.loads(capsys.readouterr().out)["error"]
    live_session(monkeypatch, lab)
    monkeypatch.setattr(live, "host_probe_problem", lambda d, *a: "SYNTHETIC: the rehearsal is missing")
    assert cli.main(["run", "--campaign", str(built)]) == 2
    error = json.loads(capsys.readouterr().out)["error"]
    assert "preflight failed" in error and "PF-06" in error and "the rehearsal is missing" in error
    assert all(not journal_of(built, r["run_id"]) for r in runs_of(built))


@needs_sandbox
def test_cli_run_refuses_when_the_rehearsal_is_missing(lab, built, monkeypatch):
    live_session(monkeypatch, lab)
    write_probe_record(built, drop=("HP-13",))
    try:
        checked = live.preflight(built)
        assert not checked["ok"]
        [probe] = [c for c in checked["checks"] if c["name"] == "host_probe"]
        assert "HP-13" in probe["detail"]
    finally:
        write_probe_record(built)   # the latest record passes again for the tests that follow


@needs_sandbox
def test_cli_run_refuses_when_the_latest_behavioral_check_failed(lab, built, monkeypatch):
    live_session(monkeypatch, lab)
    parent = built / "coordinator" / "behavioral"
    latest = max(int(p.name) for p in parent.iterdir())
    record = canonical.strict_load(parent / str(latest) / "result.json")
    failing = parent / str(latest + 1)
    failing.mkdir()
    canonical.write_once(failing / "result.json", runner._pretty({**record, "result": {**record["result"],
                                                                                      "ok": False}}))
    try:
        checked = live.preflight(built)
        [gate] = [c for c in checked["checks"] if c["name"] == "behavioral_gate"]
        assert not checked["ok"] and not gate["ok"] and f"behavioral/{latest + 1}" in gate["detail"]
        with pytest.raises(ContractError, match="preflight failed"):
            runner.run_campaign(built)
    finally:
        for path in (failing / "result.json", failing):
            path.chmod(0o755)
        (failing / "result.json").unlink()
        failing.rmdir()


@needs_sandbox
def test_preflight_reports_every_check_and_passes_for_a_ready_campaign(lab, built, monkeypatch):
    live_session(monkeypatch, lab)
    checked = live.preflight(built)
    assert [c["id"] for c in checked["checks"]] == [f"PF-{i:02d}" for i in range(1, 15)]
    assert checked["ok"], [c for c in checked["checks"] if not c["ok"]]
    monkeypatch.setenv("CLAUDECODE", "1")                    # an orchestrating session's marker
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "SYNTHETIC")
    [env] = [c for c in live.preflight(built)["checks"] if c["name"] == "coordinator_env"]
    assert not env["ok"] and env["detail"]["never_present_names"] == ["CLAUDECODE", "CLAUDE_CODE_OAUTH_TOKEN"]


# ---------------------------------------------------------------- the live runs

@pytest.fixture(scope="module")
def ran(lab, built):
    """Two SYNTHETIC live runs of the built campaign with the clean mock, through the whole path: preflight, the
    credential validation, the real behavioral gate, the per-launch proxy, the credential injection, the post-run
    sweep and checks, sealing, the live checks. The first invocation (limit 2) launches run 1 and holds before run 2
    (S10a, E-92); the recorded go opens it; the second invocation (limit 1) launches run 2, and the pause (limit)
    leaves the other six untouched."""
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        held = runner.run_campaign(built, limit=2)
        go = live.record_go_no_go(built, decision="go", decided_by="SYNTHETIC reviewer",
                                  reason="SYNTHETIC S10a review of run 1")
        result = runner.run_campaign(built, limit=1)
    runs = [r for r in held["runs"] + result["runs"] if r["action"] != "skipped"]
    return SimpleNamespace(campaign=built, held=held, go=go, result={**result, "runs": runs},
                           rids=[r["run_id"] for r in runs])


@needs_sandbox
def test_live_campaign_end_to_end_with_a_mocked_claude(lab, ran):
    campaign = ran.campaign
    assert [r["action"] for r in ran.result["runs"]] == ["sealed", "sealed"] and ran.result["stopped"] is None
    assert ran.result["paused"].startswith("limit 1") and ran.result["held"] is False
    assert ran.held["held"] is True and ran.held["paused"].startswith("S10a") and len(ran.held["runs"]) == 1
    assert ran.go["decision"] == "go" and ran.go["run_id"] == ran.rids[0] and ran.go["lc16_status"] == "pass"
    for rid in ran.rids:
        states = [r["state"] for r in journal_of(campaign, rid)]
        assert states == ["materialized", "admitted", "launched", "process_started", "exited", "sealed"]
        record = sealed_json(campaign, rid, "run.json")
        assert record["status_hint"] == "exited" and record["validity_flags"] == []
        result = sealed_json(campaign, rid, "adapter_result.json")
        assert result["validity"] == {"ok": True, "invalidating": []}
        assert result["details"]["init"]["apiKeySource"] == "none"
        assert result["details"]["bash"] == {"calls": 2, "ok": 2, "errors": 0}
        launch = sealed_json(campaign, rid, "launch.json")
        assert "CLAUDE_CODE_OAUTH_TOKEN" in launch["env_names"]
        assert {"HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy", "CLAUDE_CONFIG_DIR",
                "CLAUDE_CODE_TMPDIR"} <= set(launch["env_names"])
        call = canonical.strict_load(campaign / "runs" / rid / "host" / "launch_call.json")
        assert call["credential_env_names"] == ["CLAUDE_CODE_OAUTH_TOKEN"]
        names = {p.relative_to(campaign / "runs" / rid / "sealed").as_posix()
                 for p in (campaign / "runs" / rid / "sealed").rglob("*") if p.is_file()}
        assert {"proxy.jsonl", "host_state.json", "broker/client_env.jsonl"} <= names and "redactions.json" not in names
        assert any(n.startswith("broker/ravel-runs/") and n.endswith("/execution_state.json") for n in names)
        assert (campaign / "runs" / rid / "sealed" / "proxy.jsonl").read_bytes() == b""
        details = closing(campaign, rid)["details"]
        assert details["credential_sweep"]["clean"] is True and details["coordinator_flags"] == []
        assert details["keychain"]["persisted"] is False and details["client_env"]["credential_names"] == []
        assert details["proxy"]["requests"] == 0 and details["charge"]["usd_basis"] == "reported"
        checks = canonical.strict_load(campaign / "runs" / rid / "live_checks.json")
        failing = [c for c in checks["checks"] if c["status"] == "fail"]
        assert failing == [] and checks["stop"] is None
        lc16 = next(c for c in checks["checks"] if c["id"] == "LC-16")
        assert lc16["status"] == "pass" and abs(lc16["detail"]["recomputed"] - lc16["detail"]["reported"]) < 1e-12
        launched = next(r for r in journal_of(campaign, rid) if r["state"] == "launched")["details"]
        assert launched["host_binding_sha256"] == canonical.digest(
            canonical.strict_load(campaign / "coordinator" / runner.HOST_BINDING))   # build-time binding (R20)
        assert launched["behavioral_record_sha256"] is not None
    untouched = [r["run_id"] for r in runs_of(campaign) if r["run_id"] not in ran.rids]
    assert len(untouched) == 6 and all(not journal_of(campaign, rid) for rid in untouched)
    assert not (campaign / "coordinator" / runner.STOP_FILE).exists()
    assert not [t for t in threading.enumerate() if t.name.startswith("allowlist-proxy")]   # every proxy stopped


@needs_sandbox
def test_the_dummy_token_never_appears_in_any_sealed_file_journal_launch_record_proxy_log_or_stream_copy(lab, ran):
    """The task's required credential test: after two live launches that carried the dummy token in their environment,
    no file under the store, the subjects root or the host-state root holds it or any encoded variant."""
    roots = [lab.store, lab.roots / "smoke-built-s", lab.roots / "smoke-built-h"]
    assert files_holding(roots, lab.token) == []
    for rid in ran.rids:   # the records named in the requirement exist (and were among the files searched)
        run_dir = ran.campaign / "runs" / rid
        for path in (run_dir / "journal.jsonl", run_dir / "sealed" / "launch.json", run_dir / "sealed" / "proxy.jsonl",
                     run_dir / "sealed" / "stdout.jsonl", run_dir / "host" / "stdout.jsonl",
                     run_dir / "host" / "launch_call.json"):
            assert path.is_file(), path


@needs_sandbox
def test_build_time_binding_equals_the_first_launch_binding(ran):
    binding = canonical.strict_load(ran.campaign / "coordinator" / runner.HOST_BINDING)
    first = next(r for r in journal_of(ran.campaign, ran.rids[0]) if r["state"] == "launched")["details"]
    assert first["host_binding_sha256"] == canonical.digest(binding)
    call = canonical.strict_load(ran.campaign / "runs" / ran.rids[0] / "host" / "launch_call.json")
    at = call["argv"].index("--session-id")
    assert call["argv"][:at + 1] + [runner.PLACEHOLDER_SESSION] + call["argv"][at + 2:] == binding["argv"]


@needs_sandbox
def test_proxy_variables_are_coordinator_env_and_absent_from_the_binding(ran):
    binding = canonical.strict_load(ran.campaign / "coordinator" / runner.HOST_BINDING)
    assert not {"HTTPS_PROXY", "https_proxy", "NO_PROXY", "no_proxy"} & set(binding["extra_env"])
    admitted = next(r for r in journal_of(ran.campaign, ran.rids[0]) if r["state"] == "admitted")["details"]
    assert isinstance(admitted["proxy_port"], int)


@needs_sandbox
def test_limit_processes_n_assignments_and_leaves_the_rest_unsealed(ran):
    assert len(runner.unsealed_runs(ran.campaign)) == 6 and ran.result["paused"]


# ---------------------------------------------------------------- scenarios: one fresh campaign each

APPROVALS = iter(range(1, 10_000))


def fresh_approval(lab, **changes):
    """Another approval of the same scope (a new approved_utc: another canonical digest, so the ledger admits it)."""
    n = next(APPROVALS)
    return lab.approval(**{"approved_utc": f"2026-09-26T15:{n // 60:02d}:{n % 60:02d}Z", **changes})


def scenario(lab, name, modes, *, limit=None, budget=None, approval_changes=None, before_run=None,
             credential_file=None):
    """Build a fresh SYNTHETIC live campaign, record a passing probe gate, take the behavioral gate as passed, plant
    ``modes`` ({registry index: "mode [argument]"}) and run it under the stop rules. Returns (campaign, run ids,
    result)."""
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        campaign = build_live(lab, name, approval_record=fresh_approval(lab, **(approval_changes or {})),
                              budget=budget, credential_file=credential_file)
        write_probe_record(campaign)
        gate_passes(patch)
        rids = [r["run_id"] for r in runs_of(campaign)]
        plant(patch, {rids[i]: mode for i, mode in modes.items()})
        if before_run is not None:
            before_run(patch, campaign)
        result = runner.run_campaign(campaign, limit=limit)
    return campaign, rids, result


def build_only(lab, name, **kw):
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        campaign = build_live(lab, name, approval_record=fresh_approval(lab), **kw)
    write_probe_record(campaign)
    return campaign


def stopped_as(campaign, rule):
    stop = runner.read_stop(campaign)
    assert stop is not None and stop["rule"] == rule, stop
    return stop


def closed_by_the_stop(campaign, rids):
    for rid in rids:
        record = sealed_json(campaign, rid, "run.json")
        assert record["status_hint"] == "not_started" and "campaign stopped before this assignment" in \
            record["not_started_reason"], record
        assert closing(campaign, rid)["details"]["charge"]["usd"] == 0.0
        assert not (campaign / "runs" / rid / "host" / "launch_call.json").exists()


@needs_sandbox
@pytest.mark.parametrize("mode", ["leak_stdout", "leak_config", "leak_hex", "leak_name", "leak_proxy"])
def test_a_leaked_token_is_redacted_before_sealing_and_stops_the_campaign(lab, mode):
    campaign, rids, result = scenario(lab, f"smoke-{mode.replace('_', '-')}", {0: mode})
    stop = stopped_as(campaign, "S2")
    assert "credential_exposed" in stop["reason"]
    record = sealed_json(campaign, rids[0], "run.json")
    assert "credential_exposed" in record["validity_flags"] and record["status_hint"] == "exited"
    redactions = sealed_json(campaign, rids[0], "redactions.json")
    # E-80: no plain digest of token-bearing bytes (or of a name equal to the token) is ever sealed
    assert redactions and all("pre_sha256" not in r and canonical.is_sha256(r["post_sha256"]) and r["counts_by_variant"]
                              for r in redactions)
    assert all(r["pre_hmac_sha256"] != r["post_sha256"] for r in redactions if "pre_hmac_sha256" in r)
    assert any("pre_hmac_sha256" in r for r in redactions) or mode == "leak_name"
    expected_variant = {"leak_stdout": "raw", "leak_config": "raw", "leak_hex": "hex_lower", "leak_name": "raw",
                        "leak_proxy": "raw"}[mode]
    assert any(expected_variant in r["counts_by_variant"] for r in redactions)
    roots = [lab.store, lab.roots / f"smoke-{mode.replace('_', '-')}-s", lab.roots / f"smoke-{mode.replace('_', '-')}-h"]
    assert files_holding(roots, lab.token) == []
    checks = canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json")
    assert next(c for c in checks["checks"] if c["id"] == "LC-12")["status"] == "fail"
    assert "REVOKE THE TOKEN NOW" in checks["action"]
    closed_by_the_stop(campaign, rids[1:])
    from governance import audit
    report = audit.build_report(campaign, rids[0])
    assert any(item.startswith("integrity: credential redaction: the host credential was found and redacted")
               for item in report["unresolved_items"])
    assert report["v1_outcome"]["unsupported_claim"] is None
    if mode == "leak_stdout":   # the stop closes every other run with a v1 row
        reports = audit.audit_campaign(campaign)
        assert len(reports) == 8 and sum(r["status"] == "not_started" for r in reports) == 7
        outcomes = canonical.strict_load(runner.write_outcomes(campaign))
        assert len(outcomes["outcomes"]) == 8


@needs_sandbox
def test_a_token_visible_to_the_subject_shell_stops_the_campaign(lab):
    campaign, rids, _ = scenario(lab, "smoke-leak-child", {0: "leak_child"})
    stop = stopped_as(campaign, "S2")
    assert "credential_visible_to_subject" in stop["reason"]
    details = closing(campaign, rids[0])["details"]
    assert details["client_env"]["credential_names"] == ["CLAUDE_CODE_OAUTH_TOKEN"]
    reports = canonical.read_jsonl(campaign / "runs" / rids[0] / "sealed" / "broker" / "client_env.jsonl")[0]
    assert any("CLAUDE_CODE_OAUTH_TOKEN" in (r["names"] or []) for r in reports)
    assert files_holding([lab.store], lab.token) == []   # its name was reported, never its value
    closed_by_the_stop(campaign, rids[1:])


@needs_sandbox
def test_host_auth_failure_stops_s1(lab):
    campaign, rids, _ = scenario(lab, "smoke-auth", {0: "auth_fail"})
    stop = stopped_as(campaign, "S1")
    assert "host_auth_failed" in stop["reason"]
    closed_by_the_stop(campaign, rids[1:])


@needs_sandbox
def test_keychain_residue_check_flags_a_persisted_item(lab, tmp_path):
    found = tmp_path / "security-found"
    found.write_text("#!/bin/sh\n# SYNTHETIC: every lookup finds an item\nexit 0\n")
    found.chmod(0o755)
    campaign, rids, _ = scenario(lab, "smoke-keychain", {},
                                 before_run=lambda patch, c: patch.setattr(live, "SECURITY_COMMAND", (str(found),)))
    stop = stopped_as(campaign, "S2")
    assert "credential_persisted_keychain" in stop["reason"]
    keychain = closing(campaign, rids[0])["details"]["keychain"]
    config = keychain["checked"][0]["config_dir"]
    assert config.startswith(str(lab.roots / "smoke-keychain-h")) and config.endswith("/config")
    assert keychain["persisted"] is True and keychain["checked"][0]["service"] == live.keychain_service(config)
    assert "credential_persisted_keychain" in sealed_json(campaign, rids[0], "run.json")["validity_flags"]


@needs_sandbox
def test_proxy_log_is_sealed_and_a_host_denial_flags_and_stops(lab):
    campaign, rids, _ = scenario(lab, "smoke-proxy-other", {0: "proxy_other api.example.invalid:443"})
    stop = stopped_as(campaign, "S3")
    assert "proxy_denied_connect" in stop["reason"]
    logged = canonical.read_jsonl(campaign / "runs" / rids[0] / "sealed" / "proxy.jsonl")[0]
    assert [(d["decision"], d["reason"], d["attribution"], d["target"]) for d in logged] == [
        ("deny", "not_allowlisted", "owner", "api.example.invalid:443")]
    assert "proxy_denied_connect" in sealed_json(campaign, rids[0], "run.json")["validity_flags"]
    closed_by_the_stop(campaign, rids[1:])


@pytest.fixture(scope="module")
def mixed(lab):
    """One SYNTHETIC campaign whose allowlist also names a local echo: run 0 CONNECTs to it from the leader, run 1 from
    a child of the leader, run 2 plants a FIFO in its config dir; none of these stops the campaign."""
    echo = Echo()
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(live, "PROXY_ALLOW", ("api.anthropic.com:443", f"127.0.0.1:{echo.port}"))
            campaign, rids, result = scenario(lab, "smoke-mixed", {0: f"proxy_ok 127.0.0.1:{echo.port}",
                                                                  1: f"proxy_child 127.0.0.1:{echo.port}",
                                                                  2: "fifo_in_state"}, limit=3)
    finally:
        echo.close()
    return SimpleNamespace(campaign=campaign, rids=rids, result=result, echo=echo.port)


@needs_sandbox
def test_allowlisted_connect_from_the_leader_is_logged_allow(mixed):
    logged = canonical.read_jsonl(mixed.campaign / "runs" / mixed.rids[0] / "sealed" / "proxy.jsonl")[0]
    assert [(d["decision"], d["attribution"], d["target"]) for d in logged] == [
        ("allow", "owner", f"127.0.0.1:{mixed.echo}")]
    assert "SYNTHETIC ping" in sealed_json(mixed.campaign, mixed.rids[0], "adapter_result.json")["final_text"]
    assert sealed_json(mixed.campaign, mixed.rids[0], "run.json")["validity_flags"] == []


@needs_sandbox
def test_a_non_leader_client_is_denied_as_an_outcome_not_a_stop(mixed):
    logged = canonical.read_jsonl(mixed.campaign / "runs" / mixed.rids[1] / "sealed" / "proxy.jsonl")[0]
    assert [(d["decision"], d["reason"], d["attribution"]) for d in logged] == [("deny", "subject_client", "other")]
    details = closing(mixed.campaign, mixed.rids[1])["details"]
    assert details["info_flags"] == ["sandbox_denials_unavailable", "subject_network_attempt"]
    assert sealed_json(mixed.campaign, mixed.rids[1], "run.json")["validity_flags"] == []
    assert mixed.result["stopped"] is None and runner.read_stop(mixed.campaign) is None
    checks = canonical.strict_load(mixed.campaign / "runs" / mixed.rids[1] / "live_checks.json")
    assert next(c for c in checks["checks"] if c["id"] == "LC-23")["detail"]["subject_network_attempts"] == 1


@needs_sandbox
def test_scans_of_host_state_skip_fifos_and_respect_caps(mixed):
    """M9: a FIFO the host (or a subject through it) plants in the host state is reported, never opened blocking: the
    canary scan, the host-state manifest and the credential sweep all complete."""
    details = closing(mixed.campaign, mixed.rids[2])["details"]
    assert details["canary_scan"]["state_violations"] == ["special_file"]
    assert details["credential_sweep"]["clean"] is True and details["credential_sweep"]["incomplete"] is False
    manifest = sealed_json(mixed.campaign, mixed.rids[2], "host_state.json")
    assert [v["code"] for v in manifest["violations"]] == ["special_file"]
    assert all(f["path"] != "config/planted.fifo" for f in manifest["files"])
    assert mixed.result["stopped"] is None


@needs_sandbox
def test_real_launch_starts_and_stops_its_own_proxy_on_every_path(lab, mixed):
    """Every launch had its own proxy (a distinct port), each stopped before its run was sealed; a not_started run
    after the proxy started (a refused binding) stops it too; no proxy thread is left."""
    ports = [next(r for r in journal_of(mixed.campaign, rid) if r["state"] == "admitted")["details"]["proxy_port"]
             for rid in mixed.rids[:3]]
    assert len(set(ports)) == 3
    for rid in mixed.rids[:3]:
        assert closing(mixed.campaign, rid)["details"]["proxy"]["stop_error"] is None

    def mismatch(patch, campaign):
        path = campaign / "coordinator" / runner.HOST_BINDING
        binding = canonical.strict_load(path)
        path.chmod(0o644)
        path.write_bytes(runner._pretty({**binding, "usd_ceiling": 99.0}))
    campaign, rids, _ = scenario(lab, "smoke-binding", {}, before_run=mismatch)
    details = closing(campaign, rids[0])["details"]
    assert details["code"] == "binding_mismatch" and details["proxy"]["requests"] == 0
    assert stopped_as(campaign, "S6")["reason"] == "not_started:binding_mismatch"
    assert not [t for t in threading.enumerate() if t.name.startswith("allowlist-proxy")]


@needs_sandbox
def test_the_global_and_per_run_caps_refuse_further_launches(lab):
    """The task's required cap test: with a global cap one charged run leaves below the per-run cap, the next
    admission is refused (not_started, charge 0, never launched), the spend rule (S5) stops the campaign and every
    remaining assignment is closed without a launch."""
    budget = {**LIVE_BUDGET, "global_usd_cap": 2.001}
    campaign, rids, result = scenario(lab, "smoke-caps", {}, budget=budget,
                                      approval_changes={"caps.global_usd_cap": 2.001})
    assert sealed_json(campaign, rids[0], "run.json")["status_hint"] == "exited"
    refused = sealed_json(campaign, rids[1], "run.json")
    assert refused["status_hint"] == "not_started" and "global budget admission" in refused["not_started_reason"]
    assert not (campaign / "runs" / rids[1] / "host" / "launch_call.json").exists()
    assert stopped_as(campaign, "S5")["reason"] == "not_started:global_budget"
    closed_by_the_stop(campaign, rids[2:])
    launches = [rid for rid in rids if any(r["state"] == "launched" for r in journal_of(campaign, rid))]
    assert launches == rids[:1] and result["spent"]["usd"] < 2.001


@needs_sandbox
def test_run_after_a_stop_launches_nothing_and_a_human_stop_is_honoured_between_runs(lab, monkeypatch, capsys):
    campaign, rids, result = scenario(lab, "smoke-human", {}, limit=1)
    assert result["stopped"] is None and result["paused"] and len(runner.unsealed_runs(campaign)) == 7
    assert cli.main(["stop", "--campaign", str(campaign), "--reason", "SYNTHETIC human stop", "--by",
                     "SYNTHETIC reviewer"]) == 0
    assert json.loads(capsys.readouterr().out)["stop"]["rule"] == "S8"
    live_session(monkeypatch, lab)
    gate_passes(monkeypatch)

    def never(assignment):
        raise AssertionError("a stopped campaign must not build an adapter")
    after = runner.run_campaign(campaign, adapter_factory=never)
    assert after["stopped"]["rule"] == "S8" and runner.unsealed_runs(campaign) == []
    closed_by_the_stop(campaign, rids[1:])
    again = runner.run_campaign(campaign, adapter_factory=never)
    assert {r["action"] for r in again["runs"]} == {"skipped"}


@needs_sandbox
def test_credential_validation_failure_pauses_without_a_stop(lab, tmp_path):
    base = Path(os.path.realpath(tmp_path))
    directory = base / "cred-pause"
    directory.mkdir(mode=0o700)
    token = directory / "token"
    token.write_text("sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16) + "\n")
    token.chmod(0o600)
    campaign, rids, result = scenario(lab, "smoke-pause", {}, limit=1, credential_file=str(token))
    assert result["runs"][0]["action"] == "sealed"
    token.chmod(0o644)
    token.write_text("short\n")                  # no longer a token (and the mode check would fail too)
    token.chmod(0o600)
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        gate_passes(patch)
        with pytest.raises(runner.CredentialPause, match="paused: the host credential cannot be used"):
            runner.run_campaign(campaign)
    assert runner.read_stop(campaign) is None
    assert all(not journal_of(campaign, rid) for rid in rids[1:])   # nothing journaled for the paused runs


@needs_sandbox
def test_an_unreadable_credential_inside_the_recorder_is_not_started_with_zero_charge_and_stops(lab, tmp_path):
    base = Path(os.path.realpath(tmp_path))
    directory = base / "cred-race"
    directory.mkdir(mode=0o700)
    token = directory / "token"
    token.write_text("short\n")                  # stat-clean, but not a token: the recorder's read fails
    token.chmod(0o600)

    def race(patch, campaign):   # the run-start validation saw a good file; it changed before the launch
        patch.setattr(live, "validate_credential", lambda campaign_dir: None)
    campaign, rids, _ = scenario(lab, "smoke-race", {}, credential_file=str(token), before_run=race)
    details = closing(campaign, rids[0])["details"]
    assert details["code"] == "credential_unavailable" and details["charge"]["usd"] == 0.0
    assert "the host credential is unavailable" in details["reason"] and "short" not in details["reason"]
    assert stopped_as(campaign, "S1")["reason"] == "not_started:credential_unavailable"
    assert not (campaign / "runs" / rids[0] / "host" / "launch_call.json").exists()


# ---------------------------------------------------------------- M6: the bound launch call

def bound_campaign(host="claude_cli"):
    return SimpleNamespace(host={"adapter": host}, leaks=lambda data: [])


BOUND_ARGV = ["/opt/synthetic/claude", "-p", "--session-id", runner.PLACEHOLDER_SESSION, "--effort", "high"]
EXPECTED = {"binding": {"argv": BOUND_ARGV, "extra_env": {"DISABLE_TELEMETRY": "1", "CLAUDE_CODE_SHELL": "/bin/zsh"}},
            "per_run_env": {"CLAUDE_CONFIG_DIR": "/h/state/config", "CLAUDE_CODE_TMPDIR": "/h/state/tmp"}}
BASE_ENV = {"HOME": "/w/home", "HTTPS_PROXY": "http://127.0.0.1:5"}


def call_problems(argv=None, extra=None, drop=()):
    session = "12345678-1234-4123-8123-123456789abc"
    argv = argv or [a if a != runner.PLACEHOLDER_SESSION else session for a in BOUND_ARGV]
    env = {**BASE_ENV, **EXPECTED["binding"]["extra_env"], **EXPECTED["per_run_env"], **(extra or {})}
    for name in drop:
        env.pop(name)
    return runner._Campaign._launch_call_problems(bound_campaign(), argv, env, BASE_ENV, expected=EXPECTED,
                                                  require_expected=True)


def test_a_launch_argv_that_differs_from_the_binding_is_refused():
    assert call_problems() == []
    assert call_problems(argv=["/opt/synthetic/claude", "-p", "--session-id", "not-a-uuid", "--effort", "high"]) == [
        "the launch argv must carry exactly one --session-id followed by a canonical uuid"]
    session = "12345678-1234-4123-8123-123456789abc"
    assert call_problems(argv=["/opt/synthetic/claude", "-p", "--session-id", session, "--effort", "max"]) == [
        "the launch argv differs from the host binding written at build"]
    twice = ["/opt/synthetic/claude", "-p", "--session-id", session, "--session-id", session, "--effort", "high"]
    assert "exactly one --session-id" in call_problems(argv=twice)[0]


def test_an_added_variable_outside_the_binding_is_refused():
    assert call_problems(extra={"EXTRA_SETTING": "1"}) == [
        "the added variables differ from the binding: extra ['EXTRA_SETTING'], missing []"]
    assert call_problems(drop=["DISABLE_TELEMETRY"]) == [
        "the added variables differ from the binding: extra [], missing ['DISABLE_TELEMETRY']"]
    assert call_problems(extra={"DISABLE_TELEMETRY": "0"}) == ["DISABLE_TELEMETRY differs from its bound value"]
    found = call_problems(extra={"ANTHROPIC_API_KEY": "SYNTHETIC"})
    assert any("credential-like variables ['ANTHROPIC_API_KEY']" in p for p in found)
    assert any("never reach a real host: ['ANTHROPIC_API_KEY']" in p for p in found)
    assert runner._Campaign._launch_call_problems(bound_campaign(), BOUND_ARGV, BASE_ENV, BASE_ENV,
                                                  require_expected=True) == [
        "the launch call came before the host binding was checked"]


def test_a_per_run_directory_other_than_the_coordinators_is_refused():
    assert call_problems(extra={"CLAUDE_CONFIG_DIR": "/elsewhere/config"}) == [
        "the per-run CLAUDE_CONFIG_DIR is not the coordinator's /h/state/config"]


@needs_sandbox
def test_the_final_host_env_has_exactly_the_documented_names(ran):
    """Smoke spec §1.3: the host's environment is exactly the coordinator's names, the bound names, the per-run
    directories and the credential's name; none of the never-present names."""
    binding = canonical.strict_load(ran.campaign / "coordinator" / runner.HOST_BINDING)
    documented = ({"HOME", "LANG", "PATH", "TMPDIR", "RAVEL_TASK_ENDPOINT", "RAVEL_TASK_TOKEN", "HTTPS_PROXY",
                   "https_proxy", "NO_PROXY", "no_proxy", "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_TMPDIR",
                   "CLAUDE_CODE_OAUTH_TOKEN"} | set(binding["extra_env"]))
    assert set(binding["extra_env"]) == {
        "CLAUDE_CODE_DISABLE_AUTO_MEMORY", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "DISABLE_AUTOUPDATER",
        "ENABLE_CLAUDEAI_MCP_SERVERS", "DISABLE_TELEMETRY", "DISABLE_ERROR_REPORTING", "CLAUDE_CODE_DISABLE_FAST_MODE",
        "CLAUDE_CODE_NO_MODEL_FALLBACK", "CLAUDE_CODE_DISABLE_1M_CONTEXT", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS",
        "CLAUDE_CODE_DISABLE_ADVISOR_TOOL", "CLAUDE_CODE_MAX_RETRIES", "BASH_DEFAULT_TIMEOUT_MS", "BASH_MAX_TIMEOUT_MS",
        "ZDOTDIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB", "CLAUDE_CODE_SHELL",
        "CLAUDE_CODE_CERT_STORE", "CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR", "FORCE_PROMPT_CACHING_5M"}
    for rid in ran.rids:
        names = sealed_json(ran.campaign, rid, "launch.json")["env_names"]
        assert set(names) == documented and live.never_present(names) == []
        path = [n for n in names if n == "PATH"]
        assert path


def test_real_host_launch_reports_but_does_not_remove_unattributable_ipc(tmp_path, monkeypatch):
    """M7 (R12a): the recording launcher of a real host passes remove_unattributed_ipc=False (unattributable System V
    objects are reported for a human and flag ipc_residue); the fake host's keeps the old behaviour."""
    seen = []
    monkeypatch.setattr(isolation, "launch", lambda argv, **kw: seen.append(kw["remove_unattributed_ipc"]) or "ran")
    for real, expected in ((True, False), (False, True)):
        recorder = runner._Recorder(tmp_path / f"call-{real}.json", tmp_path / f"journal-{real}.jsonl",
                                    remove_unattributed_ipc=not real)
        assert recorder(["/bin/true"], cwd=tmp_path, env={}, profile=None, timeout_s=5,
                        stdout_path=tmp_path / f"o{real}", stderr_path=tmp_path / f"e{real}") == "ran"
    assert seen == [False, True]


def test_recorder_injects_the_credential_only_into_the_launch_env(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    directory = base / "cred"
    directory.mkdir(mode=0o700)
    token = "sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16)
    (directory / "token").write_text(token + "\n")
    (directory / "token").chmod(0o600)
    seen, proxy, owners = [], SimpleNamespace(owner_pid=None), []

    def fake_launch(argv, **kw):
        seen.append(dict(kw["env"]))
        kw["on_start"]({"pid": 4242, "pgid": 4242, "marker": None, "started_at": 1.0, "leader_start": 1.0})
        owners.append(proxy.owner_pid)
        return "ran"
    monkeypatch.setattr(isolation, "launch", fake_launch)
    admitted = []
    recorder = runner._Recorder(base / "launch_call.json", base / "journal.jsonl",
                                credential=("CLAUDE_CODE_OAUTH_TOKEN", str(directory / "token")),
                                admission=lambda env, names: admitted.append(sorted(names)) or {"ok": True,
                                                                                               "violations": []},
                                proxy=proxy, remove_unattributed_ipc=False)
    handed = {"HOME": "/w/home"}
    assert recorder(["/bin/true"], cwd=base, env=handed, profile=None, timeout_s=5, stdout_path=base / "o",
                    stderr_path=base / "e") == "ran"
    assert seen == [{"HOME": "/w/home", "CLAUDE_CODE_OAUTH_TOKEN": token}] and handed == {"HOME": "/w/home"}
    assert admitted == [["CLAUDE_CODE_OAUTH_TOKEN"]] and owners == [4242]   # the owner while the launch runs
    assert proxy.owner_pid is None             # cleared once it returned: a later client is never the owner
    call = canonical.strict_load(base / "launch_call.json")
    assert call["env_names"] == ["CLAUDE_CODE_OAUTH_TOKEN", "HOME"]
    assert call["credential_env_names"] == ["CLAUDE_CODE_OAUTH_TOKEN"]
    assert recorder.needle == token.encode()
    recorder.release()
    assert recorder.needle is None
    for path in (base / "launch_call.json", base / "journal.jsonl"):
        assert token.encode() not in path.read_bytes()


def test_an_adapter_may_not_add_the_credential_or_any_secret_named_variable(tmp_path, monkeypatch):
    monkeypatch.setattr(isolation, "launch", lambda argv, **kw: pytest.fail("nothing may launch"))
    recorder = runner._Recorder(tmp_path / "call.json", tmp_path / "journal.jsonl",
                                credential=("CLAUDE_CODE_OAUTH_TOKEN", str(tmp_path / "absent")))
    with pytest.raises(runner.LaunchRefused, match="set the credential variable CLAUDE_CODE_OAUTH_TOKEN itself"):
        recorder(["/bin/true"], cwd=tmp_path, env={"CLAUDE_CODE_OAUTH_TOKEN": "SYNTHETIC"}, profile=None,
                 timeout_s=5, stdout_path=tmp_path / "o", stderr_path=tmp_path / "e")
    with pytest.raises(runner.LaunchRefused, match="the host credential is unavailable") as refused:
        recorder(["/bin/true"], cwd=tmp_path, env={}, profile=None, timeout_s=5, stdout_path=tmp_path / "o",
                 stderr_path=tmp_path / "e")
    assert refused.value.code == "credential_unavailable" and recorder.credential_failed
    assert not (tmp_path / "call.json").exists()
    problems = runner._Campaign._launch_call_problems(bound_campaign("fake"), ["/bin/true"],
                                                      {"H": "1", "SOME_API_KEY": "x"}, {"H": "1"})
    assert problems == ["the adapter added credential-like variables ['SOME_API_KEY']; only the coordinator injects "
                        "the declared credential"]


# ---------------------------------------------------------------- M8: signals and the core limit (a coordinator subprocess)

COORDINATOR = r'''
import json, os, sys
sys.path[:0] = [sys.argv[5], sys.argv[6], sys.argv[7]]
import conftest   # the test signal guard, installed in this coordinator process as well
from governance import cli, live, runner
modes = json.loads(sys.argv[2])
original = runner._subject_files
runner._subject_files = lambda c, r: ({**original(c, r), "inputs/mock-mode.txt": modes[r["run_id"]].encode()}
                                      if r["run_id"] in modes else original(c, r))
live.SECURITY_COMMAND = tuple(json.loads(sys.argv[3]))
live.CODESIGN_COMMAND = tuple(json.loads(sys.argv[8]))
live.go_no_go_problem = lambda *a, **k: None
live.user_sysv_objects = lambda: []
live.sandbox_denials = lambda start, end, **kw: {"available": False, "count": None, "truncated": False,
                                                 "error": "SYNTHETIC"}
runner.behavioral_record = lambda *a, **k: (None, "0" * 64)
try:
    code = cli.main(["run", "--campaign", sys.argv[1], "--limit", sys.argv[4]])
finally:
    print("REFUSED " + json.dumps(conftest.REFUSED), flush=True)
sys.exit(code)
'''


def coordinator(lab, campaign, modes, limit):
    """A SYNTHETIC coordinator in its own process (cli.py run, which installs the live signal handlers and the core
    limit there, never in this test process), with the test signal guard active in it."""
    repo = HERE.parents[1]
    env = {"PATH": "/usr/bin:/bin", "HOME": os.path.expanduser("~"), "RAVEL_EVAL_LIVE": "1"}
    return subprocess.Popen([sys.executable, "-c", COORDINATOR, str(campaign), json.dumps(modes),
                             json.dumps(list(lab.security)),
                             str(limit), str(repo / "benchmarks"), str(repo / "src"), str(HERE),
                             json.dumps(list(lab.codesign))],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(repo))


@pytest.fixture(scope="module")
def signalled(lab):
    campaign = build_only(lab, "smoke-signals")
    rids = [r["run_id"] for r in runs_of(campaign)]
    modes = {rids[0]: "rlimit", rids[1]: "sleep"}
    first = coordinator(lab, campaign, modes, 1)
    out, err = first.communicate(timeout=300)
    second = coordinator(lab, campaign, modes, 1)
    journal = campaign / "runs" / rids[1] / "journal.jsonl"
    deadline, started = time.monotonic() + 120, None
    while time.monotonic() < deadline and started is None:
        records = runner.read_journal(journal) if journal.exists() else []
        started = next((r["details"] for r in records if r["state"] == "process_started"), None)
        time.sleep(0.2)
    assert started is not None, "the sleeping launch never started"
    time.sleep(1.0)
    alive_before = isolation._start_time(started["pid"]) is not None
    second.send_signal(signal.SIGTERM)   # the coordinator this test started, by its exact pid
    out2, err2 = second.communicate(timeout=120)
    return SimpleNamespace(campaign=campaign, rids=rids, first=(first.returncode, out, err),
                           second=(second.returncode, out2, err2), started=started, alive_before=alive_before)


@needs_sandbox
def test_core_limit_is_zero_for_every_real_host_launch(signalled):
    code, out, err = signalled.first
    assert code == 0 and "REFUSED []" in out, out + err   # paused at the limit: not a failure
    rlimit = canonical.strict_load(signalled.campaign / "runs" / signalled.rids[0] / "sealed" / "subject_output" /
                                   "rlimit.json")
    assert rlimit == {"core": [0, 0]}


@needs_sandbox
def test_sigterm_to_the_coordinator_still_censuses_its_launch(lab, signalled):
    code, out, err = signalled.second
    assert signalled.alive_before and code == 2 and "REFUSED []" in out, out + err
    assert '"interrupted": "signal SIGTERM"' in out
    assert isolation._start_time(signalled.started["pid"]) is None   # the launch's leader is gone
    states = [r["state"] for r in journal_of(signalled.campaign, signalled.rids[1])]
    assert states[-2:] == ["launched", "process_started"]           # a lost launch, resumed below
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        gate_passes(patch)
        result = runner.run_campaign(signalled.campaign, limit=1)
    record = sealed_json(signalled.campaign, signalled.rids[1], "run.json")
    assert record["status_hint"] == "interrupted" and "coordinator_interrupted" in record["validity_flags"]
    census = closing(signalled.campaign, signalled.rids[1])["details"]["census"]
    assert census["complete"] is True and census["survivors"] == []
    # A lost launch's System V residue is unknown (ipc_residue, S3), which outranks the lost launch itself (S7).
    checks = canonical.strict_load(signalled.campaign / "runs" / signalled.rids[1] / "live_checks.json")
    assert checks["stop"]["triggers"]["S7"] == ["coordinator_interrupted", "interrupted_crash"]
    assert result["stopped"]["rule"] == "S3" and "ipc_residue" in result["stopped"]["reason"]


# ---------------------------------------------------------------- WI-7c: host probes

def test_a_lost_probe_launch_is_censused_by_its_record(tmp_path):
    """R12c: a probe launch whose start is recorded without a close (its coordinator died) is censused by exactly that
    record before any new probe or run: its process is found and killed, and it is closed."""
    campaign = Path(os.path.realpath(tmp_path)) / "campaign"
    launch = campaign / "coordinator" / live.HOST_PROBE_DIR / "3" / "HP-04-shell"
    launch.mkdir(parents=True)
    started_at = time.time() - 0.2
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
                               stdin=subprocess.DEVNULL)
    try:
        time.sleep(0.2)
        record = {"pid": sleeper.pid, "pgid": sleeper.pid, "marker": None, "started_at": started_at,
                  "leader_start": isolation._start_time(sleeper.pid)}
        canonical.write_once(launch / "process_started.json", runner._pretty(record))
        found = live.census_lost_probes(campaign)
        assert [f["launch"] for f in found] == ["3/HP-04-shell"] and found[0]["census"]["killed"] == [sleeper.pid]
        assert sleeper.wait(timeout=10) == -signal.SIGKILL
        assert canonical.strict_load(launch / "closed.json")["lost"] is True
        assert live.census_lost_probes(campaign) == []            # closed: never censused twice
    finally:
        if sleeper.poll() is None:
            sleeper.kill()   # this test's own child, by its Popen handle
            sleeper.wait()


@pytest.fixture(scope="module")
def probed(lab):
    """host-probe of a SYNTHETIC live campaign pinned to the mock CLI: HP-01..HP-08, the dry start HP-09 and
    HP-10..HP-12 (no rehearsal: the gate stays incomplete)."""
    campaign = build_only(lab, "smoke-probed")
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        result = live.host_probe(campaign, dry_start=True)
    return SimpleNamespace(campaign=campaign, result=result,
                           record=canonical.strict_load(result["record"]))


@needs_sandbox
def test_host_probes_pass_against_the_mock_and_record_every_launch(lab, probed):
    probes = {p["id"]: p for p in probed.record["probes"]}
    assert [p["id"] for p in probed.record["probes"]] == [f"HP-{i:02d}" for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11,
                                                                                  12)]
    failed = {i: p["detail"] for i, p in probes.items() if p["required"] and not p["ok"]}
    assert failed == {} and probed.result["ok"] is True
    assert probes["HP-02"]["detail"]["writes"] == {"config": "ok", "tmp": "ok", "state_root": live.EPERM,
                                                  "probe_state": live.EPERM, "sibling": live.EPERM}
    assert probes["HP-07"]["detail"] == {"directory_present": True, "file_present": True,
                                         "stat": {"directory": live.EPERM, "credential": live.EPERM}}
    assert probes["HP-08"]["detail"]["probe"]["direct"] == live.EPERM
    assert probes["HP-08"]["detail"]["probe"]["v6"] not in (None, "connected")   # the proxy's ::1 twin is reserved
    hp06 = probes["HP-06"]["detail"]
    assert hp06["login_keychain_stat"] == live.EPERM and hp06["show_keychain_info_exit"]["unsandboxed"] == 0
    assert hp06["show_keychain_info_exit"]["real_host_profile"] not in (0, 36, 126, 127, None)
    hp09 = probes["HP-09"]["detail"]
    assert all(hp09["checks"].values()) and hp09["connects"] == [
        {"target": "api.anthropic.com:443", "attribution": "owner", "reason": "not_allowlisted"}]
    assert "RAVEL_TASK_TOKEN" in hp09["hook_names"] and "CLAUDE_CODE_OAUTH_TOKEN" not in hp09["hook_names"]
    root = probed.campaign / "coordinator" / live.HOST_PROBE_DIR / str(probed.record["probe_run"])
    launches = sorted(p.name for p in root.iterdir() if p.is_dir())
    assert "HP-09" in launches and all((root / name / "closed.json").is_file() for name in launches)
    assert all((root / name / "process_started.json").is_file() for name in launches)
    assert files_holding([probed.campaign, lab.roots / "smoke-probed-s", lab.roots / "smoke-probed-h"],
                         lab.token) == []   # the probes never read the declared credential


@needs_sandbox
def test_host_probe_records_multiprocessing_without_blocking(probed):
    hp10 = next(p for p in probed.record["probes"] if p["id"] == "HP-10")
    assert hp10["required"] is False and hp10["ok"] is False and "error" in hp10["detail"]["outcome"]
    assert probed.result["ok"] is True and probed.result["failed"] == []


@needs_sandbox
def test_host_probe_required_failure_blocks_run(lab, probed, monkeypatch):
    assert "missing ['HP-13']" in live.host_probe_problem(probed.campaign)   # a probe run without the rehearsal
    live_session(monkeypatch, lab)
    monkeypatch.setattr(live, "BASE_PROBES", live.BASE_PROBES[:6] + (
        lambda pr: live._probe("HP-07", True, False, {"SYNTHETIC": "the credential path was readable"}),)
                        + live.BASE_PROBES[7:])
    result = live.host_probe(probed.campaign)
    assert result["ok"] is False and result["failed"] == ["HP-07"]
    assert "failed ['HP-07']" in live.host_probe_problem(probed.campaign)
    gate_passes(monkeypatch)
    with pytest.raises(ContractError, match="PF-06"):
        runner.run_campaign(probed.campaign)
    assert all(not journal_of(probed.campaign, r["run_id"]) for r in runs_of(probed.campaign))


@pytest.fixture(scope="module")
def rehearsed(tmp_path_factory, lab):
    """HP-13 through host-probe --rehearse, with the campaign pinned to the rehearsal's mock CLI
    (tests/governance/mock_claude_cli.py), which speaks to the local mock Messages API."""
    base = Path(os.path.realpath(tmp_path_factory.mktemp("lab")))
    pins = base / "pins"
    pins.mkdir()
    exe = pins / "claude"
    render(HERE / "mock_claude_cli.py", exe, __MOCK_VERSION__=MOCK_VERSION, __MOCK_MODE__="clean")
    pins.chmod(0o555)
    pin = lab.pin(executable=str(exe), executable_sha256=canonical.sha256_file(exe))
    try:
        with pytest.MonkeyPatch.context() as patch:
            live_session(patch, lab)
            campaign = build_live(lab, "smoke-rehearsed", pin=pin, approval_record=fresh_approval(
                lab, **{"scope.host.executable_sha256": pin.executable_sha256}))
            result = live.host_probe(campaign, rehearse=True)
        yield SimpleNamespace(campaign=campaign, result=result, record=canonical.strict_load(result["record"]))
    finally:
        pins.chmod(0o755)


@needs_sandbox
def test_the_rehearsal_runs_through_recorded_probe_launches_and_prices_the_pin(lab, rehearsed):
    hp13 = next(p for p in rehearsed.record["probes"] if p["id"] == "HP-13")
    failures = [c for c in hp13["detail"]["checks"] if c["required"] and not c["ok"]]
    assert hp13["ok"] is True and failures == [], json.dumps(failures)[:3000]
    assert hp13["detail"]["pricing_eligible"] is True
    assert hp13["detail"]["cli_price_per_mtok"][MOCK_MODEL]["input_tokens"] == 2.0
    root = rehearsed.campaign / "coordinator" / live.HOST_PROBE_DIR / str(rehearsed.record["probe_run"])
    sessions = [p for p in root.iterdir() if p.is_dir() and p.name.startswith("HP-13-")]
    assert sessions and all((p / "process_started.json").is_file() and (p / "closed.json").is_file()
                            for p in sessions)
    assert "sk-ant-oat01-SYNTHETIC" not in json.dumps(rehearsed.record)
    assert live.cli_price_per_mtok(rehearsed.campaign) == hp13["detail"]["cli_price_per_mtok"]
    assert "missing ['HP-09']" in live.host_probe_problem(rehearsed.campaign)   # the gate needs HP-09 as well


# ---------------------------------------------------------------- §4: stop rules, WI-7d: live checks

@pytest.mark.parametrize("flag, rule", sorted(live.STOP_RULES.items()))
def test_every_listed_flag_maps_to_its_stop_rule(flag, rule):
    stop = live.stop_reason({"flags": [flag]}, [])
    assert stop["rule"] == rule and stop["reason"] == flag


@pytest.mark.parametrize("code, rule", sorted(live.NOT_STARTED_RULES.items()))
def test_live_checks_map_not_started_codes_to_stop_rules(code, rule):
    assert live.stop_reason({"flags": [], "not_started_code": code}, [])["rule"] == rule


# Every admission stage the runner journals (admission_failed ``stage``) and the not_started code its first close
# records. A resume closes the run with the stage itself as its code (runner._Campaign._resume).
ADMISSION_STAGE_CODES = {"materialization": "materialization", "workspace": "admission", "global_budget": "global_budget",
                         "broker": "broker_preparation", "proxy": "proxy_start_failed", "profile": "profile",
                         "environment": "environment", "prompt": "prompt", "treatment": "treatment", "host": "host"}


def test_every_admission_stage_the_runner_journals_is_listed():
    source = Path(runner.__file__).read_text()
    journaled = set(re.findall(r'"admission_failed", stage="([a-z_]+)"', source)) | set(
        re.findall(r'return refuse\("([a-z_]+)"', source))
    assert journaled == set(ADMISSION_STAGE_CODES)


@pytest.mark.parametrize("stage, code", sorted(ADMISSION_STAGE_CODES.items()))
def test_a_resumed_admission_failure_maps_to_the_rule_of_its_first_close(stage, code):
    """E-67, E-70: a stage code (the resume's) stops the campaign under the same rule as the code the first close
    would have recorded, so a coordinator dying between admission_failed and not_started changes nothing."""
    resumed = live.stop_reason({"flags": [], "not_started_code": stage}, [])
    first = live.stop_reason({"flags": [], "not_started_code": code}, [])
    assert resumed is not None and first is not None and resumed["rule"] == first["rule"]


@needs_sandbox
@pytest.mark.parametrize("stage, rule", [("workspace", "S3"), ("broker", "S7"), ("proxy", "S7")])
def test_a_resumed_admission_failure_stops_the_campaign(lab, monkeypatch, stage, rule):
    """The coordinator died after journaling admission_failed and before not_started (SYNTHETIC journal lines): the
    resume closes the run with the stage as its code, the stop rule fires and every other assignment is closed without
    a launch."""
    campaign = build_only(lab, f"smoke-resume-{stage}")
    rids = [r["run_id"] for r in runs_of(campaign)]
    journal = campaign / "runs" / rids[0] / "journal.jsonl"
    runner._record(journal, "materialized", opaque_handle="SYNTHETIC")
    runner._record(journal, "admission_failed", stage=stage,
                   reason=f"SYNTHETIC {stage} failure; the coordinator died before its not_started record")
    live_session(monkeypatch, lab)
    gate_passes(monkeypatch)

    def never(assignment):
        raise AssertionError("a run closed on resume, or after a stop, never builds an adapter")
    result = runner.run_campaign(campaign, adapter_factory=never)
    assert closing(campaign, rids[0])["details"]["code"] == stage
    assert result["stopped"]["rule"] == rule
    assert stopped_as(campaign, rule)["reason"] == f"not_started:{stage}"
    closed_by_the_stop(campaign, rids[1:])


def test_live_checks_map_flags_to_stop_rules():
    """The spec's §4 table, and its two special cases: an auth failure beside a host-attributed proxy deny is
    isolation (S3), and a lost launch is S7; outcomes (timeouts, budget exhaustion, subject network attempts,
    permission denials) never stop; the most severe rule wins."""
    table = {"S1": ["host_auth_failed", "host_usage_limited"],
             "S2": ["credential_exposed", "credential_visible_to_subject", "credential_sweep_incomplete",
                    "credential_persisted_keychain", "init_api_key_source_unexpected"],
             "S3": ["proxy_denied_connect", "proxy_owner_unknown", "canary_in_transcript", "web_tools_in_init",
                    "init_tools_unexpected", "web_tool_used", "web_requests_reported", "mcp_servers_present",
                    "plugins_present", "init_permission_mode_mismatch", "survivors_after_kill", "census_incomplete",
                    "ipc_residue"],
             "S4": ["code_drift_during_run", "kernel_fingerprint_mismatch", "stage_worker_mismatch",
                    "interpreter_mismatch"],
             "S5": ["cost_recompute_mismatch", "fast_mode_used", "cost_zero_with_usage"],
             "S6": ["init_model_mismatch", "main_model_substituted", "init_version_mismatch", "init_unverified",
                    "shell_tool_failed", "task_token_missing_in_shell"],
             "S7": ["proxy_upstream_error", "proxy_stop_failed", "broker_stop_failed", "raw_streams_missing",
                    "launch_unrecorded"]}
    for rule, flags in table.items():
        for flag in flags:
            assert live.STOP_RULES[flag] == rule, flag
    assert live.stop_reason({"flags": ["host_auth_failed", "proxy_denied_connect"]}, [])["triggers"] == {
        "S3": ["host_auth_failed", "proxy_denied_connect"]}
    assert live.stop_reason({"flags": []}, [{"state": "interrupted_crash"}])["rule"] == "S7"
    for outcome in ("host_budget_exhausted", "cost_over_run_cap", "subject_network_attempt", "permission_denied",
                    "sandbox_denial_in_tool_output", "auxiliary_model_usage", "shell_snapshot_missing",
                    "sandbox_denials_unavailable", "cost_basis_not_list", "model_refusal_reported"):
        assert live.stop_reason({"flags": [outcome]}, []) is None, outcome
    assert live.stop_reason({"flags": ["shell_tool_failed", "credential_exposed", "fast_mode_used"]},
                            [])["rule"] == "S2"
    assert live.stop_reason({"flags": [], "not_started_code": "stopped"}, []) is None


@needs_sandbox
def test_live_checks_and_costs_through_the_cli(lab, ran, capsys):
    assert cli.main(["live-checks", "--campaign", str(ran.campaign), "--costs"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["runs"]) == 2 and out["stop"] is None
    costs = out["costs"]
    rows = [r for r in costs["runs"] if r["state"] == "exited"]
    assert len(rows) == 2 and all(r["checks"] == [] for r in rows)
    assert all(abs(r["recomputed_cost_usd"] - r["reported_total_cost_usd"]) < 1e-12 for r in rows)
    assert costs["worst_case"]["k"] == 0 and costs["caps"]["global_usd_cap"] == 16.0
    assert "quota usage" in costs["meaning"]


def test_cost_recompute_uses_only_the_measured_rates():
    usage = {MOCK_MODEL: {"inputTokens": 1_000_000, "outputTokens": 100_000, "cacheCreationInputTokens": 0,
                          "cacheReadInputTokens": 0, "costUSD": 3.0}}
    assert live.recompute_cost(usage, RATES) == pytest.approx(3.0)
    assert live.recompute_cost(usage, {}) is None                          # no provider price is ever assumed
    dated = {f"{MOCK_MODEL}-20260901": usage[MOCK_MODEL]}
    assert live.recompute_cost(dated, RATES) == pytest.approx(3.0)        # a dated snapshot of the pin


@needs_sandbox
def test_cli_build_live_prints_the_campaign_and_never_opens_the_credential(lab, monkeypatch, capsys, tmp_path):
    live_session(monkeypatch, lab)
    approval_file = Path(os.path.realpath(tmp_path)) / "approval.json"
    approval_file.write_bytes(json.dumps(fresh_approval(lab), indent=2).encode())
    opened = []
    real_open = os.open

    def watched(path, *args, **kwargs):
        if os.fspath(path) == str(lab.cred):
            opened.append(path)
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(os, "open", watched)
    argv = ["build-live", "--store", str(lab.store), "--campaign-id", "smoke-cli", "--created-utc", CREATED,
            "--subjects-root", str(lab.roots / "smoke-cli-s"), "--host-state-root", str(lab.roots / "smoke-cli-h"),
            "--executable", str(lab.exe), "--executable-sha256", lab.sha, "--host-version", MOCK_VERSION,
            "--model", MOCK_MODEL, "--effort", "high", "--credential-file", str(lab.cred), "--approval-file",
            str(approval_file), "--seed", "11", "--schedule-seed", "7", "--task", "lf-b", "--task", "lf-d",
            "--usd-per-run", "2", "--seconds-per-run", "900", "--global-seconds-cap", "7680", "--max-turns", "100"]
    assert cli.main(argv) == 0, capsys.readouterr().out
    out = json.loads(capsys.readouterr().out)
    campaign = Path(out["campaign_dir"])
    assert out["synthetic"] is True and out["runs"] == 8 and out["credential_present"] is True
    assert out["approval_sha256"] == canonical.sha256_file(approval_file) == \
        canonical.strict_load(campaign / "campaign.json")["authorization"]["reference_sha256"]
    assert out["host_binding_sha256"] == canonical.sha256_file(campaign / "coordinator" / runner.HOST_BINDING)
    assert opened == []
    assert cli.main(argv) == 2   # the same campaign id (and approval) again: refused, nothing changed
    assert "refusing to overwrite existing campaign directory" in json.loads(capsys.readouterr().out)["error"]
    argv[argv.index("smoke-cli")] = "smoke-cli-again"
    assert cli.main(argv) == 2   # the same approval under another id: single-use
    assert "single-use" in json.loads(capsys.readouterr().out)["error"]
    assert not (lab.store / "synthetic" / "smoke-cli-again").exists()


def test_the_canary_scan_reads_the_streams_and_the_host_state_without_value_canaries(tmp_path):
    """WI-7b, M9: the host's raw streams and every host-state file are scanned for the random campaign and family
    canaries and the fixed fragments (not the oracle values, which a correct transcript legitimately prints); a FIFO
    in the state is reported, never opened."""
    base = Path(os.path.realpath(tmp_path))
    host_dir, state = base / "host", base / "state"
    (state / "config").mkdir(parents=True)
    host_dir.mkdir()
    campaign = SimpleNamespace(canary="RAVEL-EVAL-CANARY-" + "a" * 32, family_canary="RAVEL-EVAL-CANARY-" + "b" * 32)
    (host_dir / "stdout.jsonl").write_text('{"text": "the observed limit is 3.456789012 events"}\n')
    (host_dir / "stderr.txt").write_text("")
    (state / "config" / "session.jsonl").write_text("SYNTHETIC transcript\n")
    os.mkfifo(state / "config" / "planted.fifo")
    record, flags, _ = runner._Campaign._canary_check(campaign, host_dir, state)
    assert record["hits"] == [] and flags == set() and record["state_violations"] == ["special_file"]
    (state / "config" / "leak.txt").write_text("SYNTHETIC " + campaign.family_canary)
    (host_dir / "stdout.jsonl").write_text(runner.DEFINITION_CANARY)
    (host_dir / runner.HOST_STATE_MANIFEST).unlink()
    record, flags, _ = runner._Campaign._canary_check(campaign, host_dir, state)
    assert record["hits"] == ["host/stdout.jsonl", "host_state/config/leak.txt"] and flags == {"canary_in_transcript"}


# ================================================================ the 2026-09-27 review of the live path

# ---------------------------------------------------------------- stop rules fail closed (E-74)

def test_every_invalidating_flag_has_a_stop_rule_and_no_rule_is_an_outcome():
    from governance.adapters import base
    assert base.INVALIDATING_FLAGS <= set(live.STOP_RULES)
    assert not set(live.STOP_RULES) & live.OUTCOME_FLAGS
    for flag in base.INVALIDATING_FLAGS:
        assert live.stop_reason({"flags": [flag]}, []) is not None, flag


def emitted_flags() -> set:
    """Every flag literal the adapters, the runner and the live checks can set (a source scan)."""
    root, found = Path(runner.__file__).parent, set()
    pattern = re.compile(r'flags\.(?:add|append)\("([a-z0-9_]+)"\)|flags\s*\|=\s*\{"([a-z0-9_]+)"\}')
    for name in ("runner.py", "live.py", "adapters/claude_cli.py", "adapters/base.py"):
        for match in pattern.finditer((root / name).read_text()):
            found.add(match.group(1) or match.group(2))
    return found


def test_every_flag_the_harness_can_emit_is_classified():
    """E-74: a flag is a stop or an outcome, never neither; a new flag must be classified here or it stops (S7)."""
    flags = emitted_flags() | {"sandbox_denials_unavailable", "subject_network_attempt", "shell_snapshot_missing",
                               "coordinator_interrupted", "adapter_error", runner.CODE_DRIFT_FLAG, runner.CLOCK_FLAG}
    assert len(flags) > 40
    unclassified = sorted(flags - set(live.STOP_RULES) - live.OUTCOME_FLAGS)
    assert unclassified == []


def test_an_unclassified_flag_an_unknown_code_or_a_silent_failure_stops_s7():
    stop = live.stop_reason({"flags": ["synthetic_new_flag"]}, [])
    assert stop["rule"] == "S7" and stop["reason"] == "unclassified:synthetic_new_flag"
    assert live.stop_reason({"flags": [], "not_started_code": "synthetic_new_code"}, [])["rule"] == "S7"
    assert live.stop_reason({"flags": [], "not_started_code": None, "status_hint": "not_started"},
                            [])["reason"] == "not_started:without_code"
    assert live.stop_reason({"flags": [], "not_started_code": live.STOP_CLOSURE_CODE}, []) is None
    failing = {"flags": [], "checks": [{"id": "LC-99", "status": "fail", "detail": {"flags": []}}]}
    assert live.stop_reason(failing, [])["reason"] == "live_check_failed:LC-99"
    covered = {"flags": ["shell_tool_failed"], "checks": [{"id": "LC-09", "status": "fail",
                                                           "detail": {"flags": ["shell_tool_failed"]}}]}
    assert live.stop_reason(covered, [])["triggers"] == {"S6": ["shell_tool_failed"]}
    for flag in ("normalization_failed", "schema_errors", "session_id_mismatch", "no_init_event"):
        assert live.stop_reason({"flags": [flag]}, [])["rule"] in ("S6", "S7"), flag
    assert live.stop_reason({"flags": ["init_tools_unrecognized"]}, [])["rule"] == "S3"
    assert live.stop_reason({"flags": sorted(live.OUTCOME_FLAGS)}, []) is None


def test_hp09_and_hp13_gate_on_every_init_flag_a_paid_run_stops_on():
    from governance import rehearsal
    for flags in (live.HP09_INIT_FLAGS, rehearsal.INIT_FLAGS):
        assert {"plugins_present", "mcp_servers_present", "init_skills_unexpected", "init_agents_unexpected",
                "init_tools_unrecognized"} <= set(flags)
        assert all(live.STOP_RULES[f] in ("S2", "S3", "S6") for f in flags)


# ---------------------------------------------------------------- stop evaluation is idempotent (E-78)

@needs_sandbox
def test_a_stop_lost_between_seal_and_stop_is_rederived_before_anything_launches(lab):
    """Probe A of the review: run 0 leaks the dummy token (S2); the coordinator is interrupted after run 0 is sealed
    and before its stop rules are evaluated. The next invocation re-derives the stop from the sealed evidence before
    any gate or launch: stop.json is S2 and nothing else launches; preflight PF-07 already shows it."""
    real, calls = live.live_checks, {"n": 0}

    def interrupted(campaign_dir, run_id, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise runner.CoordinatorInterrupted("SYNTHETIC SIGHUP between the seal and the stop evaluation")
        return real(campaign_dir, run_id, **kw)
    with pytest.raises(runner.CoordinatorInterrupted):
        scenario(lab, "smoke-lost-stop", {0: "leak_stdout"},
                 before_run=lambda patch, c: patch.setattr(live, "live_checks", interrupted))
    campaign = lab.store / "synthetic" / "smoke-lost-stop"
    rids = [r["run_id"] for r in runs_of(campaign)]
    assert "credential_exposed" in sealed_json(campaign, rids[0], "run.json")["validity_flags"]
    assert runner.read_stop(campaign) is None
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        gate_passes(patch)
        [pf07] = [c for c in live.preflight(campaign)["checks"] if c["id"] == "PF-07"]
        assert pf07["ok"] is False and pf07["detail"][0]["stop"]["rule"] == "S2"
        assert runner.read_stop(campaign) is None   # preflight only reads

        def never(assignment):
            raise AssertionError("a stopped campaign must not build an adapter")
        result = runner.run_campaign(campaign, adapter_factory=never)
    stop = stopped_as(campaign, "S2")
    assert stop["run_id"] == rids[0] and "credential_exposed" in stop["reason"]
    assert result["triggers"][0]["run_id"] == rids[0] and result["triggers"][0]["written"] is True
    assert result["triggers"][0]["action"] == live.REVOKE
    closed_by_the_stop(campaign, rids[1:])


@needs_sandbox
def test_live_checks_that_raise_stop_the_campaign_s7(lab):
    def boom(campaign_dir, run_id, **kw):
        raise ValueError("SYNTHETIC failure inside the live checks")
    campaign, rids, result = scenario(lab, "smoke-eval-fails", {},
                                      before_run=lambda patch, c: patch.setattr(live, "live_checks", boom))
    stop = stopped_as(campaign, "S7")
    assert stop["reason"] == "live_checks_failed:ValueError" and stop["run_id"] == rids[0]
    closed_by_the_stop(campaign, rids[1:])


@needs_sandbox
def test_a_human_stop_during_a_run_keeps_the_automated_trigger(lab, monkeypatch, capsys):
    """Probe E of the review: `cli.py stop` lands while run 0 runs; run 0's S2 trigger then finds the stop in place.
    Nothing raises, stop.json stays the human's, the trigger is recorded, and `run` prints the REVOKE action."""
    real = live.live_checks

    def human_stop_first(campaign_dir, run_id, **kw):
        if runner.read_stop(campaign_dir) is None:
            runner.write_stop(campaign_dir, run_id=None, rule="S8", reason="SYNTHETIC human stop during run 0",
                              set_by="SYNTHETIC reviewer")
        return real(campaign_dir, run_id, **kw)
    campaign, rids, result = scenario(lab, "smoke-human-race", {0: "leak_stdout"},
                                      before_run=lambda patch, c: patch.setattr(live, "live_checks", human_stop_first))
    stopped_as(campaign, "S8")
    [trigger] = result["triggers"]
    assert (trigger["run_id"], trigger["rule"], trigger["written"]) == (rids[0], "S2", False)
    assert trigger["action"] == live.REVOKE
    assert canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json")["action"] == live.REVOKE
    closed_by_the_stop(campaign, rids[1:])
    monkeypatch.setattr(cli, "install_live_handlers", lambda: None)
    live_session(monkeypatch, lab)
    gate_passes(monkeypatch)
    assert cli.main(["run", "--campaign", str(campaign)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["stopped"]["rule"] == "S8" and out["action"] == live.REVOKE


def test_stops_are_written_once_atomically_and_never_overwritten(tmp_path):
    (tmp_path / "coordinator").mkdir()
    first, written = runner.record_stop(tmp_path, run_id=None, rule="S8", reason="SYNTHETIC first", set_by="a")
    again, rewritten = runner.record_stop(tmp_path, run_id="0" * 64, rule="S2", reason="SYNTHETIC second",
                                          set_by="b")
    assert written is True and rewritten is False and again == first == runner.read_stop(tmp_path)
    with pytest.raises(ContractError, match="refusing to overwrite the stop already in place"):
        runner.write_stop(tmp_path, run_id=None, rule="S7", reason="SYNTHETIC third", set_by="c")
    racers = tmp_path / "race"
    (racers / "coordinator").mkdir(parents=True)
    outcomes, barrier = [], threading.Barrier(6)

    def race(i):
        barrier.wait()
        outcomes.append(runner.record_stop(racers, run_id=None, rule="S8", reason=f"SYNTHETIC {i}", set_by=str(i))[1])
    threads = [threading.Thread(target=race, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(outcomes) == [False] * 5 + [True]
    assert [p.name for p in (racers / "coordinator").iterdir()] == [runner.STOP_FILE]   # no temporary left


# ---------------------------------------------------------------- --only and open launches (E-79)

@needs_sandbox
def test_only_is_refused_for_a_real_host(lab, built, monkeypatch, capsys):
    live_session(monkeypatch, lab)
    rid = runs_of(built)[0]["run_id"]
    with pytest.raises(ContractError, match="only: refused for a real host"):
        runner.run_campaign(built, only=[rid])
    monkeypatch.setattr(cli, "install_live_handlers", lambda: None)
    assert cli.main(["run", "--campaign", str(built), "--only", rid]) == 2
    assert "--only is refused" in json.loads(capsys.readouterr().out)["error"]


@needs_sandbox
def test_an_open_launch_counts_at_the_per_run_cap_in_global_admission(lab):
    """A launch on record without a closing record (a lost launch not yet resumed) is charged at c by admission: with
    a global cap of 3.9 USD and c = 2, a SYNTHETIC open launch of run 1 leaves 1.9, so run 0 is refused (S5)."""
    def open_launch(patch, campaign):
        rid = runs_of(campaign)[1]["run_id"]
        runner._record(campaign / "runs" / rid / "journal.jsonl", "launched", SYNTHETIC="an open launch")
    budget = {**LIVE_BUDGET, "global_usd_cap": 3.9}
    campaign, rids, _ = scenario(lab, "smoke-open-launch", {}, budget=budget,
                                 approval_changes={"caps.global_usd_cap": 3.9}, before_run=open_launch)
    refused = sealed_json(campaign, rids[0], "run.json")
    assert refused["status_hint"] == "not_started" and "global budget admission" in refused["not_started_reason"]
    assert stopped_as(campaign, "S5")["reason"] == "not_started:global_budget"
    assert not (campaign / "runs" / rids[0] / "host" / "launch_call.json").exists()


# ---------------------------------------------------------------- the per-user approval ledger (E-77)

@needs_sandbox
def test_one_approval_builds_one_campaign_whatever_the_store(lab, monkeypatch, tmp_path, ledger_home):
    """Probe D of the review: the same approval cannot build a second campaign in another store."""
    live_session(monkeypatch, lab)
    record = fresh_approval(lab)
    build_live(lab, "smoke-store-a", approval_record=record)
    other = Path(os.path.realpath(tmp_path)) / "store-b"
    monkeypatch.setattr(lab, "store", other)
    with pytest.raises(ContractError, match="single-use"):
        build_live(lab, "smoke-store-b", approval_record=record)
    assert not (other / "synthetic" / "smoke-store-b").exists() and not (other / live.APPROVAL_LEDGER).exists()
    assert live.ledger_dir() == ledger_home and (ledger_home / live.APPROVAL_LEDGER).is_file()


def test_the_ledger_directory_and_file_are_private(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    loose.chmod(0o755)
    with pytest.raises(ContractError, match="mode 0700"):
        with live.claim_approval(loose, approval_sha256="d" * 64, campaign_id="x", created_utc=CREATED):
            pytest.fail("a claim in a group- or world-readable directory")
    fresh = tmp_path / "fresh"
    with live.claim_approval(fresh, approval_sha256="d" * 64, campaign_id="x", created_utc=CREATED):
        pass
    assert stat.S_IMODE(fresh.stat().st_mode) == 0o700
    assert stat.S_IMODE((fresh / live.APPROVAL_LEDGER).stat().st_mode) == 0o600
    assert live.read_approval_ledger(fresh)[0]["campaign_id"] == "x"


# ---------------------------------------------------------------- HP-06 and HP-07 (E-73, E-83)

@pytest.fixture(scope="module")
def probe_campaign(lab):
    """A SYNTHETIC live campaign whose credential file is not minted yet (its directory exists), loaded for direct
    probe calls."""
    base = lab.base / "hp07-cred"
    base.mkdir(mode=0o700)
    campaign = build_only(lab, "smoke-probe-direct", credential_file=str(base / "token"))
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        loaded = runner._Campaign(campaign)
    (campaign / "coordinator" / live.HOST_PROBE_DIR).mkdir(exist_ok=True)
    return SimpleNamespace(campaign=campaign, loaded=loaded, token=base / "token")


@needs_sandbox
def test_hp07_denies_the_directory_before_minting_and_the_file_after(lab, probe_campaign, monkeypatch):
    live_session(monkeypatch, lab)
    token = probe_campaign.token
    before = live._hp07(live._ProbeRun(probe_campaign.loaded, 21))
    assert before["ok"] is True, before
    assert before["detail"] == {"directory_present": True, "file_present": False, "stat": {"directory": live.EPERM}}
    write_probe_record(probe_campaign.campaign, hp07=before["detail"])
    assert live.host_probe_problem(probe_campaign.campaign, str(token)) is None   # nothing minted: the gate holds
    token.write_text("sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16) + "\n")
    token.chmod(0o600)
    try:
        assert "run host-probe again" in live.host_probe_problem(probe_campaign.campaign, str(token))
        after = live._hp07(live._ProbeRun(probe_campaign.loaded, 23))
        assert after["ok"] is True and after["detail"] == {"directory_present": True, "file_present": True,
                                                           "stat": {"directory": live.EPERM,
                                                                    "credential": live.EPERM}}
    finally:
        token.unlink()


@needs_sandbox
def test_hp07_fails_without_the_credential_directory(lab, tmp_path, monkeypatch):
    """An absent path under a deny root answers ENOENT, which shows nothing: HP-07 needs the directory (S2)."""
    campaign = build_only(lab, "smoke-probe-nodir",
                          credential_file=str(Path(os.path.realpath(tmp_path)) / "absent" / "token"))
    live_session(monkeypatch, lab)
    (campaign / "coordinator" / live.HOST_PROBE_DIR).mkdir(exist_ok=True)
    found = live._hp07(live._ProbeRun(runner._Campaign(campaign), 2))
    assert found["ok"] is False and found["detail"]["directory_present"] is False
    assert found["detail"]["stat"]["directory"] == "FileNotFoundError:2"


@needs_sandbox
def test_hp06_needs_the_named_keychain_reachable_outside_and_denied_inside(lab, probe_campaign, monkeypatch):
    live_session(monkeypatch, lab)
    passing = live._hp06(live._ProbeRun(probe_campaign.loaded, 14))
    assert passing["ok"] is True, passing
    assert passing["detail"]["show_keychain_info_exit"]["unsandboxed"] == 0
    assert passing["detail"]["nonexistent_service_lookup_exit"] == {"unsandboxed": 44, "real_host_profile": 44}
    monkeypatch.setattr(live, "login_keychain", lambda: PYTHON)   # a file the profile lets the subject read
    reachable = live._hp06(live._ProbeRun(probe_campaign.loaded, 15))
    assert reachable["ok"] is False and reachable["detail"]["show_keychain_info_exit"]["real_host_profile"] == 0


# ---------------------------------------------------------------- probe launches and interrupts (E-81)

def test_an_interrupted_probe_launch_is_left_for_the_census(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    for name in ("coordinator/host_probe", "subjects", "states"):
        (base / name).mkdir(parents=True)
    campaign = SimpleNamespace(dir=base, subjects_root=base / "subjects", host_state_root=base / "states",
                               config={"subject_python": PYTHON}, host={"executable": "/bin/true"},
                               host_launch={"credential": {"env_name": "CLAUDE_CODE_OAUTH_TOKEN"}})
    pr = live._ProbeRun(campaign, 1)
    started = {}

    def interrupted_launch(argv, *, on_start, **kw):
        floor = time.time()
        started["proc"] = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                           start_new_session=True, stdin=subprocess.DEVNULL)
        time.sleep(0.2)
        on_start({"pid": started["proc"].pid, "pgid": started["proc"].pid, "marker": None, "started_at": floor,
                  "leader_start": isolation._start_time(started["proc"].pid)})
        raise runner.CoordinatorInterrupted("SYNTHETIC SIGTERM while the probe launch runs")
    monkeypatch.setattr(isolation, "launch", interrupted_launch)
    try:
        with pytest.raises(runner.CoordinatorInterrupted):
            pr.launch("HP-04-shell", ["/bin/true"], cwd=base, env={}, profile=None)
        launch = base / "coordinator" / "host_probe" / "1" / "HP-04-shell"
        assert (launch / "process_started.json").is_file() and (launch / "error.json").is_file()
        assert not (launch / "closed.json").exists()   # left for the census, never closed by the interrupted run
        found = live.census_lost_probes(base)
        assert [f["launch"] for f in found] == ["1/HP-04-shell"] and found[0]["census"]["killed"] == [
            started["proc"].pid]
        assert started["proc"].wait(timeout=10) == -signal.SIGKILL
    finally:
        if "proc" in started and started["proc"].poll() is None:
            started["proc"].kill()   # this test's own child, by its Popen handle
            started["proc"].wait()


def test_interrupts_are_held_inside_a_deferred_section_and_raised_once_it_ends():
    reached = []
    with pytest.raises(runner.CoordinatorInterrupted, match="first"):
        with isolation.interrupts_deferred():
            with isolation.interrupts_deferred():
                isolation.interrupt(runner.CoordinatorInterrupted("first"))
                isolation.interrupt(runner.CoordinatorInterrupted("second"))
                reached.append("inner")
            reached.append("outer")   # the inner section ends without raising: the outermost one does
    assert reached == ["inner", "outer"]
    with pytest.raises(runner.CoordinatorInterrupted, match="now"):
        isolation.interrupt(runner.CoordinatorInterrupted("now"))


def test_an_interrupt_during_the_start_is_raised_after_it_is_recorded_and_the_launch_killed(tmp_path):
    """E-81: a SIGTERM that arrives between the subject's start and its record is held until on_start has recorded
    it; it is then raised, and the launch's own finally kills the recorded process."""
    recorded = []

    def on_start(record):
        recorded.append(record)
        isolation.interrupt(runner.CoordinatorInterrupted("SYNTHETIC SIGTERM during the start"))
        recorded.append("on_start finished")
    with pytest.raises(runner.CoordinatorInterrupted):
        isolation.launch(["/bin/sleep", "30"], cwd=str(tmp_path), env={}, profile=None, timeout_s=60,
                         stdout_path=str(tmp_path / "o"), stderr_path=str(tmp_path / "e"), on_start=on_start)
    assert recorded[1] == "on_start finished" and isolation._start_time(recorded[0]["pid"]) is None


# ---------------------------------------------------------------- resume, pauses and post-run failures

@needs_sandbox
@pytest.mark.parametrize("replaced", [False, True])
def test_a_resumed_lost_launch_sweeps_only_for_the_token_it_used(lab, tmp_path, replaced):
    """The launch records a KEYED fingerprint of its token (never a plain hash); a resume re-reads the file and
    sweeps only when the fingerprint matches, else the sweep is incomplete (S2), e.g. after a re-mint."""
    base = Path(os.path.realpath(tmp_path)) / "cred-fp"
    base.mkdir(mode=0o700)
    token = base / "token"
    first = "sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16)
    token.write_text(first + "\n")
    token.chmod(0o600)
    real, calls = runner._Campaign._post_run, {"n": 0}

    def lost(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise runner.CoordinatorInterrupted("SYNTHETIC SIGTERM after the launch, before its closing record")
        return real(self, *a, **k)
    name = f"smoke-fingerprint-{int(replaced)}"
    with pytest.raises(runner.CoordinatorInterrupted):
        scenario(lab, name, {}, credential_file=str(token),
                 before_run=lambda patch, c: patch.setattr(runner._Campaign, "_post_run", lost))
    campaign = lab.store / "synthetic" / name
    rids = [r["run_id"] for r in runs_of(campaign)]
    call = canonical.strict_load(campaign / "runs" / rids[0] / "host" / "launch_call.json")
    fingerprint = call["credential_fingerprint"]
    assert canonical.is_sha256(fingerprint) and first not in json.dumps(call)
    assert fingerprint not in (hashlib.sha256(first.encode()).hexdigest(),
                               hashlib.sha256((first + "\n").encode()).hexdigest())
    if replaced:   # re-minted between the lost launch and its resume
        token.write_text("sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16) + "\n")
    with pytest.MonkeyPatch.context() as patch:
        live_session(patch, lab)
        gate_passes(patch)
        runner.run_campaign(campaign, limit=1)
    sweep = closing(campaign, rids[0])["details"]["credential_sweep"]
    if replaced:
        assert sweep["incomplete"] is True and "no longer holds the token this launch used" in sweep["note"]
        assert stopped_as(campaign, "S2")["reason"] == "credential_sweep_incomplete"
    else:
        assert sweep["incomplete"] is False and sweep["clean"] is True
        assert runner.read_stop(campaign)["rule"] != "S2"


@needs_sandbox
def test_a_credential_that_fails_between_assignments_pauses_without_a_stop(lab):
    calls, real = {"n": 0}, live.validate_credential

    def flaky(campaign_dir):
        calls["n"] += 1
        if calls["n"] >= 3:   # the run start (1) and run 0 (2) pass; before run 1 the file is unusable
            raise runner.CredentialPause("paused: the host credential cannot be used (SYNTHETIC); fix the file")
        return real(campaign_dir)
    with pytest.raises(runner.CredentialPause):
        scenario(lab, "smoke-flaky-credential", {},
                 before_run=lambda patch, c: patch.setattr(live, "validate_credential", flaky))
    campaign = lab.store / "synthetic" / "smoke-flaky-credential"
    rids = [r["run_id"] for r in runs_of(campaign)]
    assert sealed_json(campaign, rids[0], "run.json")["status_hint"] == "exited"
    assert runner.read_stop(campaign) is None and all(not journal_of(campaign, rid) for rid in rids[1:])


@needs_sandbox
@pytest.mark.parametrize("step, record, flag", [
    ("_keychain_check", "keychain", "credential_persisted_keychain"),
    ("_client_env_check", "client_env", "credential_visible_to_subject"),
    ("_canary_check", "canary_scan", "canary_in_transcript"),
])
def test_a_post_run_check_that_raises_sets_its_conservative_flag(lab, step, record, flag):
    def boom(*a, **k):
        raise OSError("SYNTHETIC failure inside a post-run check")
    campaign, rids, _ = scenario(lab, f"smoke-step-{record.replace('_', '-')}", {}, limit=1,
                                 before_run=lambda patch, c: patch.setattr(runner._Campaign, step, boom))
    details = closing(campaign, rids[0])["details"]
    assert "SYNTHETIC failure" in details[record]["error"] and flag in details["coordinator_flags"]
    assert flag in sealed_json(campaign, rids[0], "run.json")["validity_flags"]
    stop = runner.read_stop(campaign)
    assert stop is not None and flag in [f for fs in live.stop_reason(
        canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json"), [])["triggers"].values() for f in fs]


@needs_sandbox
def test_a_probe_record_that_does_not_price_the_pin_is_refused(lab, built):
    write_probe_record(built, pricing=False)
    try:
        assert "HP-13 does not show the pin pricing its model" in live.host_probe_problem(built, str(lab.cred))
    finally:
        write_probe_record(built)


# ---------------------------------------------------------------- the task client, plugins and host config

@needs_sandbox
def test_reading_the_task_client_and_the_builtin_plugin_are_outcomes_not_stops(lab):
    campaign, rids, result = scenario(lab, "smoke-read-client", {0: "read_client"}, limit=1)
    assert result["stopped"] is None and runner.read_stop(campaign) is None
    checks = canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json")
    lc = {c["id"]: c for c in checks["checks"]}
    assert lc["LC-10"]["status"] == "pass" and lc["LC-06"]["status"] == "pass"
    assert lc["LC-06"]["detail"]["builtin_plugins"] == ["agents-md@builtin"]
    config = closing(campaign, rids[0])["details"]["host_config"]
    assert config == {"present": False, "keys": [], "credential_shaped": []}


@needs_sandbox
def test_a_plugin_besides_the_builtin_one_stops_s3(lab):
    campaign, rids, _ = scenario(lab, "smoke-extra-plugin", {0: "extra_plugin"})
    assert "plugins_present" in stopped_as(campaign, "S3")["reason"]
    closed_by_the_stop(campaign, rids[1:])


def test_the_host_config_check_lists_key_names_only(tmp_path):
    state = tmp_path / "state"
    (state / "config").mkdir(parents=True)
    (state / "config" / ".claude.json").write_text(json.dumps({
        "numStartups": 1, "oauthAccount": {"emailAddress": "SYNTHETIC@example.invalid"},
        "primaryApiKey": "SYNTHETIC-VALUE-NEVER-RECORDED"}))
    record, flags, info = runner._Campaign._host_config_check(None, state)
    assert flags == {"host_config_credential_shaped"} and info == set()   # E-92: a stop (S2), no longer only recorded
    assert live.STOP_RULES["host_config_credential_shaped"] == "S2"
    assert record["keys"] == ["numStartups", "oauthAccount", "primaryApiKey", "oauthAccount.emailAddress"]
    assert record["credential_shaped"] == ["oauthAccount", "primaryApiKey", "oauthAccount.emailAddress"]
    assert "SYNTHETIC-VALUE" not in json.dumps(record) and "example.invalid" not in json.dumps(record)
    (state / "config" / ".claude.json").write_text(json.dumps({   # the keys 2.1.281 wrote against the mock API
        "firstStartTime": "SYNTHETIC", "machineID": "SYNTHETIC", "userID": "SYNTHETIC", "migrationVersion": 1,
        "pluginUsage": {"agents-md@builtin": 1}, "cachedExtraUsageDisabledReason": None}))
    record, flags, _ = runner._Campaign._host_config_check(None, state)
    assert flags == set() and record["credential_shaped"] == []


# ---------------------------------------------------------------- costs (E-76) and the catalog entry (H-27)

def cost_result(model_usage, geo=()):
    return ({"events": [{"data": {"type": "result", "modelUsage": model_usage}}]},
            {"cost_accounting": {"reported_total_cost_usd": sum(v["costUSD"] for v in model_usage.values())},
             "inference_geo": list(geo)})


def usage_of(inputs, cost):
    return {"inputTokens": inputs, "outputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0,
            "costUSD": cost}


def test_lc16_compares_the_pinned_share_when_an_auxiliary_model_is_unpriced():
    result, details = cost_result({MOCK_MODEL: usage_of(1_000_000, 2.0), "claude-aux-synthetic": usage_of(10, 0.5)})
    facts, flags = live._cost_facts(result, details, RATES, {}, MOCK_MODEL)
    assert flags == {"cost_unverified_auxiliary"} and facts["pinned_share"] == {MOCK_MODEL: [2.0, 2.0]}
    assert facts["recomputed"] is None and live.stop_reason({"flags": sorted(flags)}, []) is None
    result, details = cost_result({MOCK_MODEL: usage_of(1_000_000, 2.5), "claude-aux-synthetic": usage_of(10, 0.5)})
    assert "cost_recompute_mismatch" in live._cost_facts(result, details, RATES, {}, MOCK_MODEL)[1]


def test_lc16_applies_the_measured_geography_multiplier_or_leaves_the_recompute_unverified():
    result, details = cost_result({MOCK_MODEL: usage_of(1_000_000, 2.2)}, geo=["us"])
    facts, flags = live._cost_facts(result, details, RATES, {"us": 1.1}, MOCK_MODEL)
    assert flags == set() and facts["recomputed"] == pytest.approx(2.2) and facts["multiplier"] == 1.1
    facts, flags = live._cost_facts(result, details, RATES, {}, MOCK_MODEL)   # "us" reported, no measured multiplier
    assert flags == set() and facts["recomputed"] is None and facts["multiplier"] is None
    assert live.geo_multiplier([], {}) == 1.0 and live.geo_multiplier(["us", "eu"], {"us": 1.1}) is None


@needs_sandbox
def test_the_worst_case_uses_a_full_turn_bound(ran):
    worst = live.costs(ran.campaign)["worst_case"]
    bound = (1000 * RATES[MOCK_MODEL]["input_tokens"] + live.MAX_OUTPUT_FALLBACK * RATES[MOCK_MODEL]["output_tokens"]) \
        / 1_000_000
    assert worst["T_bound_usd"] == pytest.approx(bound) and worst["T_estimate_usd"] == pytest.approx(bound)
    assert worst["T_estimate_usd"] > worst["T_average_usd"]
    # E-94: retried requests join the worst case, which is the envelope every approval states
    assert worst["formula"] == "G + (k+1+r)*T" and worst["r"] == 0 and worst["k"] == 0
    assert worst["usd"] == pytest.approx(16.0 + bound) and worst["envelope"] == contracts.SMOKE_SPEND_ENVELOPE


def test_the_catalog_entry_is_read_from_the_pinned_bytes(tmp_path):
    exe = Path(os.path.realpath(tmp_path)) / "claude"
    render(HERE / "mock_claude_cli.py", exe, __MOCK_VERSION__=MOCK_VERSION, __MOCK_MODE__="clean")
    assert live.catalog_entry(exe, MOCK_MODEL) == {"tier": "tier_2_10", "rates": RATES[MOCK_MODEL], "entries": 1,
                                                   "tables": 1, "other_occurrences": 0}
    assert live.catalog_entry(exe, "claude-synthetic-6") is None
    # the real bundle also lists the id in UI model lists without a pricing tier: those are not catalog entries
    listed = exe.with_name("listed")
    listed.write_bytes(b'[{id:"claude-synthetic-5",thinking:{type:"effort",effort:"high"}},{id:"x"}]\n'
                       + exe.read_bytes() + b'\n{id:"claude-synthetic-5",name:"Synthetic 5",section:"main"}\n')
    assert live.catalog_entry(listed, MOCK_MODEL) == {"tier": "tier_2_10", "rates": RATES[MOCK_MODEL], "entries": 1,
                                                      "tables": 1, "other_occurrences": 2}
    conflicting = exe.with_name("conflicting")
    conflicting.write_bytes(exe.read_bytes() + b'\n{id:"claude-synthetic-5",family:"x",pricing:"tier_5_25"}\n')
    assert live.catalog_entry(conflicting, MOCK_MODEL) is None   # two entries naming different tiers


@needs_sandbox
def test_catalog_rates_need_the_rehearsal(lab, built, monkeypatch, capsys):
    live_session(monkeypatch, lab)
    assert cli.main(["host-probe", "--campaign", str(built), "--catalog-rates"]) == 2
    assert "needs --rehearse" in json.loads(capsys.readouterr().out)["error"]


# ---------------------------------------------------------------- the pinned .app and the proxy's IPv6 twin

def test_an_app_pin_whose_bundle_parent_is_writable_is_refused(lab, tmp_path):
    parent = Path(os.path.realpath(tmp_path)) / "claude-code-9.9.9"
    macos = parent / "claude.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = macos / "claude"
    exe.write_text("#!/bin/sh\necho SYNTHETIC\n")
    exe.chmod(0o555)
    pin = lab.pin(executable=str(exe), executable_sha256=canonical.sha256_file(exe))
    host_launch = live.default_host_launch(host_state_root=str(lab.roots / "hosts-app"), credential_file=str(lab.cred),
                                           pin=pin)
    for directory in (macos, macos.parent, macos.parent.parent):
        directory.chmod(0o555)
    try:
        found = runner._pinned_binary_problems(pin, host_launch, [])
        assert len(found) == 1 and str(parent) in found[0] and "without write bits" in found[0]
        parent.chmod(0o555)
        assert runner._pinned_binary_problems(pin, host_launch, []) == []
    finally:
        for directory in (parent, macos.parent.parent, macos.parent, macos):
            directory.chmod(0o755)


def test_the_proxy_holds_its_ipv6_twin_and_nothing_serves_it(tmp_path):
    proxy = allowlist_proxy.AllowlistProxy(["127.0.0.1:9"], log_path=tmp_path / "proxy.jsonl")
    proxy.start()
    try:
        other = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        with other, pytest.raises(OSError):
            other.bind(("::1", proxy.port))
        # Nothing serves the twin: macOS drops a SYN to a bound, non-listening socket (the connect times out)
        with pytest.raises(OSError):
            socket.create_connection(("::1", proxy.port), timeout=2).close()
    finally:
        proxy.stop()
    assert proxy.decisions == []
    holder = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    holder.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    with holder:
        holder.bind(("::1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        with pytest.raises(allowlist_proxy.PortTaken):
            allowlist_proxy.reserve_ipv6_twin(port)
        taken = allowlist_proxy.AllowlistProxy(["127.0.0.1:9"], log_path=tmp_path / "taken.jsonl", port=port)
        with pytest.raises(OSError, match="twin"):
            taken.start()


def test_a_stalled_upstream_lookup_never_outlives_stop(monkeypatch):
    release = threading.Event()

    def stalled(*args, **kwargs):   # a lookup that hangs; it never reaches a name service (no egress in tests)
        release.wait(30)
        raise OSError("SYNTHETIC: no name service in this test")
    monkeypatch.setattr(allowlist_proxy.socket, "getaddrinfo", stalled)
    stopping = threading.Event()
    try:
        started = time.monotonic()
        with pytest.raises(socket.timeout):
            allowlist_proxy._connect(("synthetic.invalid", 443), 0.3, stopping)
        stopping.set()
        with pytest.raises(OSError, match="stopping"):
            allowlist_proxy._connect(("synthetic.invalid", 443), 30.0, stopping)
        assert time.monotonic() - started < 5
    finally:
        release.set()


def test_a_never_present_name_passed_through_from_the_coordinator_is_refused():
    """The never-present check of the bound call covers the whole final environment, not only the names an adapter
    added: a name the coordinator's own environment passed through is refused too (the added-names check cannot
    see it)."""
    session = "12345678-1234-4123-8123-123456789abc"
    argv = [a if a != runner.PLACEHOLDER_SESSION else session for a in BOUND_ARGV]
    base = {**BASE_ENV, "ANTHROPIC_BASE_URL": "http://127.0.0.1:9"}
    env = {**base, **EXPECTED["binding"]["extra_env"], **EXPECTED["per_run_env"]}
    added = set(env) - set(base)
    assert added == set(EXPECTED["binding"]["extra_env"]) | set(EXPECTED["per_run_env"])
    assert runner._bound_call_problems(argv, env, added, EXPECTED) == [
        "the launch environment holds names that never reach a real host: ['ANTHROPIC_BASE_URL']"]


# ================================================================ the second 2026-09-27 review (E-89 to E-99)

# ---------------------------------------------------------------- the ledger's own directory (E-89)

def test_the_ledger_has_its_own_directory_under_the_0755_parent_the_procedure_leaves(tmp_path):
    """smoke-request S3's `mkdir -p` leaves ~/.local/share/ravel-eval 0755 (the umask). The former ledger directory WAS
    that directory, so the first real claim was refused; the ledger now has approvals/ of its own, created 0700."""
    parent = Path(os.path.realpath(tmp_path)) / "ravel-eval"
    (parent / "hosts" / "claude-code-2.1.281").mkdir(parents=True)
    parent.chmod(0o755)
    with pytest.raises(ContractError, match="mode 0700"):   # the former layout: refused, nothing written
        with live.claim_approval(parent, approval_sha256="e" * 64, campaign_id="x", created_utc=CREATED):
            pytest.fail("a claim in the 0755 directory S3 leaves")
    ledger = parent / "approvals"
    with live.claim_approval(ledger, approval_sha256="e" * 64, campaign_id="x", created_utc=CREATED):
        pass
    assert stat.S_IMODE(ledger.stat().st_mode) == 0o700 and stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE((ledger / live.APPROVAL_LEDGER).stat().st_mode) == 0o600
    assert [e["campaign_id"] for e in live.read_approval_ledger(ledger)] == ["x"]
    source = Path(live.__file__).read_text()   # the module fixture patches LEDGER_DIR; the default is in the source
    assert 'LEDGER_DIR = "~/.local/share/ravel-eval/approvals"' in source


@pytest.mark.parametrize("layout", ["group_writable", "missing", "symlink"])
def test_a_ledger_parent_that_others_can_write_or_that_is_missing_is_refused(tmp_path, layout):
    base = Path(os.path.realpath(tmp_path))
    parent = base / "ravel-eval"
    if layout == "group_writable":
        parent.mkdir()
        parent.chmod(0o775)
    elif layout == "symlink":
        (base / "elsewhere").mkdir()
        os.symlink(base / "elsewhere", parent)
    with pytest.raises(ContractError, match="parent"):
        with live.claim_approval(parent / "approvals", approval_sha256="e" * 64, campaign_id="x",
                                 created_utc=CREATED):
            pytest.fail("a claim under an unsafe parent")
    assert not (base / "elsewhere" / "approvals").exists() and not (parent / "approvals").exists()


@needs_sandbox
def test_a_build_claims_its_approval_under_a_parent_laid_out_as_s3_leaves_it(built, ledger_home):
    assert stat.S_IMODE(ledger_home.parent.stat().st_mode) == 0o755 and (ledger_home.parent / "hosts").is_dir()
    assert stat.S_IMODE(ledger_home.stat().st_mode) == 0o700
    assert "smoke-built" in [e["campaign_id"] for e in live.read_approval_ledger()]


# ---------------------------------------------------------------- the pin's code signature (E-90)

GET_TASK_ALLOW = "<key>com.apple.security.get-task-allow</key><true/>"


def test_the_pin_must_carry_the_hardened_runtime_and_no_get_task_allow(tmp_path, monkeypatch):
    exe = Path(os.path.realpath(tmp_path)) / "claude"
    exe.write_text("SYNTHETIC binary\n")
    for command, problem in ((codesign_stand_in(), None),
                             (codesign_stand_in(flags="0x2(adhoc)"), "hardened runtime"),
                             (codesign_stand_in(extra=GET_TASK_ALLOW), "get-task-allow"),
                             (codesign_stand_in(extra="<key>x</key>"), "entitlements cannot be read"),
                             (("/usr/bin/false",), "not validly signed")):
        monkeypatch.setattr(live, "CODESIGN_COMMAND", command)
        found = live.code_signature(exe)
        if problem is None:
            assert found["problems"] == [] and found["hardened_runtime"] is True and found["get_task_allow"] is False
        else:
            assert found["problems"] and any(problem in p for p in found["problems"]), found


@pytest.mark.skipif(sys.platform != "darwin", reason="codesign is macOS")
def test_the_real_codesign_output_is_parsed():
    """The display-only codesign of a platform binary (no hardened runtime flag): the real output format parses."""
    found = live.code_signature("/bin/ls")
    assert found["flags"] is not None and found["hardened_runtime"] is False
    assert any("hardened runtime" in p for p in found["problems"])


@needs_sandbox
def test_build_and_preflight_refuse_a_pin_whose_signature_leaves_the_task_port_open(lab, built, monkeypatch):
    live_session(monkeypatch, lab)
    monkeypatch.setattr(live, "CODESIGN_COMMAND", codesign_stand_in(extra=GET_TASK_ALLOW))
    with pytest.raises(ContractError, match="code signature does not protect the host process"):
        build_live(lab, "smoke-task-port", approval_record=fresh_approval(lab))
    assert not (lab.store / "synthetic" / "smoke-task-port").exists()
    [pf04] = [c for c in live.preflight(built)["checks"] if c["id"] == "PF-04"]
    assert pf04["ok"] is False and pf04["detail"]["get_task_allow"] is True


# ---------------------------------------------------------------- init skills and agents (E-91), HP-09's init gate

@needs_sandbox
def test_a_skill_the_pin_does_not_ship_stops_s3(lab):
    campaign, rids, _ = scenario(lab, "smoke-extra-skill", {0: "extra_skill"})
    assert "init_skills_unexpected" in stopped_as(campaign, "S3")["reason"]
    checks = canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json")
    assert next(c for c in checks["checks"] if c["id"] == "LC-06")["status"] == "fail"
    closed_by_the_stop(campaign, rids[1:])


def plant_probe_mode(monkeypatch, mode):
    """SYNTHETIC: every probe workspace carries the mock CLI's mode file (inputs/mock-mode.txt)."""
    original = live._ProbeRun.workspace

    def planted(self, label):
        ws = original(self, label)
        (ws / "inputs").mkdir()
        (ws / "inputs" / "mock-mode.txt").write_text(mode)
        return ws
    monkeypatch.setattr(live._ProbeRun, "workspace", planted)


@needs_sandbox
@pytest.mark.parametrize("mode, flag, n", [("extra_plugin", "plugins_present", 41),
                                          ("extra_skill", "init_skills_unexpected", 42),
                                          ("extra_agent", "init_agents_unexpected", 43)])
def test_hp09_fails_on_an_init_flag_a_paid_run_would_stop_on(lab, probe_campaign, monkeypatch, mode, flag, n):
    """The review's mutation (`init_matches` forced true) passed the whole suite: HP-09 must itself fail when the init
    lists what a paid run stops on (H-26), before any token exists."""
    live_session(monkeypatch, lab)
    plant_probe_mode(monkeypatch, mode)
    found = live._hp09(live._ProbeRun(probe_campaign.loaded, n))
    assert found["ok"] is False and found["detail"]["checks"]["init_matches"] is False
    assert found["detail"]["init_flags"] == [flag]
    assert all(v for k, v in found["detail"]["checks"].items() if k != "init_matches"), found["detail"]["checks"]


# ---------------------------------------------------------------- HP-06's unsandboxed control (E-73)

@needs_sandbox
def test_hp06_fails_when_the_named_keychain_is_unreachable_unsandboxed_too(lab, probe_campaign, monkeypatch):
    """The control keeps HP-06 from passing vacuously (a wrong path, or a keychain moved or renamed, fails the sandboxed
    query for reasons that have nothing to do with the sandbox): an unsandboxed answer other than 0 or 36 fails it."""
    live_session(monkeypatch, lab)
    real = live._security
    monkeypatch.setattr(live, "_security", lambda *a, **k: 50 if a[:1] == ("show-keychain-info",) else real(*a, **k))
    found = live._hp06(live._ProbeRun(probe_campaign.loaded, 16))
    exits = found["detail"]["show_keychain_info_exit"]
    assert found["ok"] is False and exits["unsandboxed"] == 50
    assert found["detail"]["login_keychain_stat"] == live.EPERM and exits["real_host_profile"] not in (0, 36, 126, 127)


# ---------------------------------------------------------------- the S10a gate (E-92)

@needs_sandbox
def test_s10a_holds_every_launch_after_run_1_until_a_go_that_needs_lc16_verified(lab, monkeypatch, capsys):
    campaign, rids, _ = scenario(lab, "smoke-s10a", {}, limit=1)
    assert live.go_no_go_problem(campaign).startswith("S10a: run 1")
    live_session(monkeypatch, lab)
    [pf14] = [c for c in live.preflight(campaign)["checks"] if c["id"] == "PF-14"]
    assert pf14["ok"] is False and "go-no-go" in pf14["detail"]
    monkeypatch.setattr(runner, "behavioral_record", lambda *a, **k: (None, "0" * 64))
    with pytest.raises(ContractError, match="PF-14"):
        runner.run_campaign(campaign)
    assert [r for r in runs_of(campaign) if journal_of(campaign, r["run_id"])] == runs_of(campaign)[:1]
    monkeypatch.setattr(live, "cli_price_per_mtok", lambda d: {})   # the recompute cannot be verified: LC-16 warn
    with pytest.raises(ContractError, match="LC-16 is warn"):
        live.record_go_no_go(campaign, decision="go", decided_by="SYNTHETIC reviewer", reason="SYNTHETIC review")
    assert live.read_go_no_go(campaign) is None
    assert cli.main(["go-no-go", "--campaign", str(campaign), "--decision", "go", "--by", "SYNTHETIC reviewer",
                     "--reason", "SYNTHETIC review", "--accept-unverified-cost", "E-SYNTHETIC-9"]) == 0
    record = json.loads(capsys.readouterr().out)["go_no_go"]
    assert record["lc16_status"] == "warn" and record["accepted_unverified_cost"] == "E-SYNTHETIC-9"
    assert record["run_id"] == rids[0] and record["host_config"] == {"present": False, "keys": [],
                                                                      "credential_shaped": []}
    assert any(p.startswith("config/shell-snapshots/") for p in record["host_state_files"])
    assert live.go_no_go_problem(campaign) is None
    with pytest.raises(ContractError, match="already recorded"):
        live.record_go_no_go(campaign, decision="no-go", decided_by="SYNTHETIC", reason="SYNTHETIC again")
    monkeypatch.undo()
    with pytest.MonkeyPatch.context() as patch:   # the go opens run 2 (the real gate: no bypass)
        live_session(patch, lab)
        patch.setattr(runner, "behavioral_record", lambda *a, **k: (None, "0" * 64))
        result = runner.run_campaign(campaign, limit=1)
    assert [r["action"] for r in result["runs"]] == ["skipped", "sealed"] and result["held"] is False


@needs_sandbox
def test_a_no_go_stops_the_campaign_s8(lab, monkeypatch, capsys):
    campaign, rids, _ = scenario(lab, "smoke-no-go", {}, limit=1)
    assert cli.main(["go-no-go", "--campaign", str(campaign), "--decision", "no-go", "--by", "SYNTHETIC reviewer",
                     "--reason", "SYNTHETIC: the host wrote something unexpected"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["go_no_go"]["decision"] == "no-go" and out["stop"]["rule"] == "S8"
    assert "S10a no-go" in stopped_as(campaign, "S8")["reason"]
    assert "'no-go'" in live.go_no_go_problem(campaign)
    live_session(monkeypatch, lab)
    gate_passes(monkeypatch)
    runner.run_campaign(campaign)
    closed_by_the_stop(campaign, rids[1:])


def test_a_go_names_the_first_launched_run_and_its_seal(tmp_path, monkeypatch):
    """A go record whose run or evidence digest is not the first launched run's current seal opens nothing."""
    campaign = Path(os.path.realpath(tmp_path))
    (campaign / "coordinator").mkdir()
    monkeypatch.setattr(live, "first_launched_run", lambda d: ("a" * 64, True))
    monkeypatch.setattr(runner, "sealed_evidence", lambda d: "b" * 64)
    record = {"schema_version": 1, "time_utc": CREATED, "run_id": "a" * 64, "evidence_sha256": "b" * 64,
              "decision": "go", "decided_by": "SYNTHETIC", "reason": "SYNTHETIC", "lc16_status": "pass",
              "accepted_unverified_cost": None, "host_config": None, "host_state_files": []}
    path = campaign / "coordinator" / live.GO_NO_GO
    for changed, problem in (({}, None), ({"evidence_sha256": "c" * 64}, "does not name"),
                             ({"run_id": "d" * 64}, "does not name"), ({"decision": "no-go"}, "'no-go'")):
        path.write_bytes(runner._pretty({**record, **changed}))
        found = live.go_no_go_problem(campaign)
        assert (found is None) if problem is None else (problem in found), found
    path.write_bytes(runner._pretty({**record, "decided_by": ""}))
    with pytest.raises(ContractError, match="not a go/no-go record"):
        live.go_no_go_problem(campaign)
    monkeypatch.setattr(live, "first_launched_run", lambda d: ("a" * 64, False))   # a lost run 1 is resumed first
    assert live.go_no_go_problem(campaign) is None


@needs_sandbox
def test_account_fields_in_the_hosts_config_stop_s2_and_print_revoke(lab):
    campaign, rids, _ = scenario(lab, "smoke-account-config", {0: "account_config"})
    stop = stopped_as(campaign, "S2")
    assert "host_config_credential_shaped" in stop["reason"]
    checks = canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json")
    lc12 = next(c for c in checks["checks"] if c["id"] == "LC-12")
    assert lc12["status"] == "fail" and lc12["detail"]["host_config_credential_shaped"] == [
        "oauthAccount", "oauthAccount.emailAddress"]
    assert checks["action"] == live.REVOKE and "example.invalid" not in json.dumps(checks)
    closed_by_the_stop(campaign, rids[1:])


# ---------------------------------------------------------------- the per-run ceiling (E-93)

def ceiling_result(max_output=32_000, per_message_input=50_000):
    return {"events": [{"data": {"type": "result", "modelUsage": {MOCK_MODEL: {"maxOutputTokens": max_output}}}}],
            "usage": {"per_message": [{"input_tokens": per_message_input}]}}


def test_an_overshoot_within_one_turn_is_an_outcome_and_a_larger_one_stops_s5():
    turn = (50_000 * 2.0 + 32_000 * 10.0) / 1_000_000   # 0.42 USD at the measured rates
    for reported, subtype, rates, geo, beyond in (
            (1.9, "success", RATES, [], False),                            # under the cap: nothing to check
            (2.3, "error_max_budget_usd", RATES, [], False),                # 0.3 over: within one turn
            (2.3, "success", RATES, [], False),
            (3.0, "success", RATES, [], True),                              # 1.0 over: the ceiling did not hold
            (2.44, "success", RATES, ["us"], False),                        # 0.44 < 0.42 x 1.1 (the measured "us")
            (2.44, "success", RATES, ["eu"], False),                        # unmeasured: the largest measured one
            (2.3, "success", {}, [], True),                                 # no rates, not the host's own stop
            (2.3, "error_max_budget_usd", {}, [], False)):
        details = {"cost_accounting": {"reported_total_cost_usd": reported}, "result_subtype": subtype,
                   "inference_geo": geo}
        facts, flags = live._overshoot_facts(ceiling_result(), details, rates, {"us": 1.1}, MOCK_MODEL, 2.0)
        assert (flags == {"cost_overshoot_beyond_turn"}) is beyond and facts["beyond_one_turn"] is beyond, facts
    assert facts["turn_bound_usd"] is None and live._overshoot_facts(ceiling_result(), details, RATES, {}, MOCK_MODEL,
                                                                     2.0)[0]["turn_bound_usd"] == pytest.approx(turn)
    assert live.stop_reason({"flags": ["cost_over_run_cap", "host_budget_exhausted"]}, []) is None
    stop = live.stop_reason({"flags": ["cost_over_run_cap", "cost_overshoot_beyond_turn"]}, [])
    assert stop["rule"] == "S5" and stop["reason"] == "cost_overshoot_beyond_turn"


@needs_sandbox
def test_a_run_that_overshoots_its_cap_by_more_than_a_turn_stops_the_campaign_s5(lab):
    campaign, rids, _ = scenario(lab, "smoke-overspend", {0: "spend 6.0"})
    assert stopped_as(campaign, "S5")["reason"] == "cost_overshoot_beyond_turn"
    checks = canonical.strict_load(campaign / "runs" / rids[0] / "live_checks.json")
    lc16 = next(c for c in checks["checks"] if c["id"] == "LC-16")
    assert lc16["status"] == "fail" and lc16["detail"]["ceiling"]["overshoot_usd"] == pytest.approx(4.0)
    closed_by_the_stop(campaign, rids[1:])
    capped, capped_rids, result = scenario(lab, "smoke-overspend-capped", {0: "spend_capped 2.5"}, limit=1)
    assert result["stopped"] is None and runner.read_stop(capped) is None   # one crossing turn: an outcome
    flags = set(canonical.strict_load(capped / "runs" / capped_rids[0] / "live_checks.json")["flags"])
    assert {"cost_over_run_cap", "host_budget_exhausted"} <= flags and "cost_overshoot_beyond_turn" not in flags


# ---------------------------------------------------------------- a launch resumed under a stop (E-95), quarantine (E-99)

@needs_sandbox
def test_a_lost_launch_resumed_under_a_human_stop_is_evaluated_and_prints_revoke(lab, tmp_path, monkeypatch, capsys):
    """The documented recovery for a resume that cannot pass preflight (`stop`, then `run`) seals the lost launch under
    the stop; its S2 finding (a sweep that cannot search a re-minted token) is recorded beside the stop and `run`
    prints REVOKE. The unswept raw streams are quarantined, never sealed."""
    base = Path(os.path.realpath(tmp_path)) / "cred-stop"
    base.mkdir(mode=0o700)
    token = base / "token"
    token.write_text("sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16) + "\n")
    token.chmod(0o600)
    real, calls = runner._Campaign._post_run, {"n": 0}

    def lost(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise runner.CoordinatorInterrupted("SYNTHETIC SIGTERM after the launch, before its closing record")
        return real(self, *a, **k)
    with pytest.raises(runner.CoordinatorInterrupted):
        scenario(lab, "smoke-stop-resume", {}, credential_file=str(token),
                 before_run=lambda patch, c: patch.setattr(runner._Campaign, "_post_run", lost))
    campaign = lab.store / "synthetic" / "smoke-stop-resume"
    rids = [r["run_id"] for r in runs_of(campaign)]
    assert (campaign / "runs" / rids[0] / "host" / "stdout.jsonl").is_file()
    token.write_text("sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16) + "\n")   # re-minted before the resume
    runner.write_stop(campaign, run_id=None, rule="S8", reason="SYNTHETIC: the resume cannot pass preflight",
                      set_by="SYNTHETIC reviewer")
    monkeypatch.setattr(cli, "install_live_handlers", lambda: None)
    live_session(monkeypatch, lab)
    gate_passes(monkeypatch)
    assert cli.main(["run", "--campaign", str(campaign)]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["stopped"]["rule"] == "S8" and out["action"] == live.REVOKE
    [trigger] = [t for t in out["triggers"] if t["run_id"] == rids[0]]
    assert trigger["rule"] == "S2" and trigger["written"] is False and trigger["action"] == live.REVOKE
    assert "credential_sweep_incomplete" in trigger["reason"]
    run_dir = campaign / "runs" / rids[0]
    assert closing(campaign, rids[0])["details"]["quarantined_streams"] == ["stdout.jsonl", "stderr.txt"]
    assert (run_dir / "quarantine" / "stdout.jsonl").is_file() and not (run_dir / "host" / "stdout.jsonl").exists()
    assert (run_dir / "sealed" / "stdout.jsonl").read_bytes() == b""
    assert "raw_streams_missing" in sealed_json(campaign, rids[0], "run.json")["validity_flags"]
    closed_by_the_stop(campaign, rids[1:])


# ---------------------------------------------------------------- unclean probe launches (E-96)

def test_census_uncleanliness_is_read_from_every_kind_of_record():
    assert not live.census_unclean({"complete": True, "survivors": []})
    assert not live.census_unclean({"census_complete": True, "survivors": []})   # a completed launch's close
    for record in ({"complete": False}, {"complete": True, "survivors": [4242]}, {"census_complete": False},
                   {"census_complete": True, "survivors": [4242]}, None, "x", {}):
        assert live.census_unclean(record), record
    found = [{"launch": "1/a", "census": {"complete": True, "survivors": []}},
             {"launch": "1/b", "census": {"complete": False}}]
    assert live.census_problems(found) == ["1/b"]


def test_an_unclean_probe_launch_is_censused_again_until_clean(tmp_path):
    """A probe launch whose recorded census was incomplete (or a completed launch that left survivors) is censused
    again by its record at every host-probe and run, never forgotten once closed."""
    campaign = Path(os.path.realpath(tmp_path)) / "campaign"
    lost = campaign / "coordinator" / live.HOST_PROBE_DIR / "2" / "HP-09"
    done = campaign / "coordinator" / live.HOST_PROBE_DIR / "2" / "HP-04-shell"
    lost.mkdir(parents=True)
    done.mkdir()
    started_at = time.time() - 0.2
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True,
                               stdin=subprocess.DEVNULL)
    try:
        time.sleep(0.2)
        record = {"pid": sleeper.pid, "pgid": sleeper.pid, "marker": None, "started_at": started_at,
                  "leader_start": isolation._start_time(sleeper.pid)}
        canonical.write_once(lost / "process_started.json", runner._pretty(record))
        canonical.write_once(lost / "closed.json", runner._pretty(
            {"lost": True, "census": {"complete": False, "note": "SYNTHETIC: an earlier census could not search"}}))
        finished = {**record, "pid": 999_999, "pgid": 999_999, "leader_start": None}   # a completed, clean launch
        canonical.write_once(done / "process_started.json", runner._pretty(finished))
        canonical.write_once(done / "closed.json", runner._pretty({"exit_code": 0, "survivors": [],
                                                                  "census_complete": True}))
        found = live.census_lost_probes(campaign)
        assert [(f["launch"], f["recensus"]) for f in found] == [("2/HP-09", 1)]
        assert found[0]["census"]["killed"] == [sleeper.pid] and live.census_problems(found) == []
        assert sleeper.wait(timeout=10) == -signal.SIGKILL
        assert canonical.strict_load(lost / "recensus-1.json")["census"]["complete"] is True
        assert live.census_lost_probes(campaign) == []            # clean now: never censused again
    finally:
        if sleeper.poll() is None:
            sleeper.kill()   # this test's own child, by its Popen handle
            sleeper.wait()


def test_a_probe_record_with_an_unclean_launch_is_no_gate(tmp_path):
    campaign = Path(os.path.realpath(tmp_path))
    (campaign / "coordinator").mkdir()
    record = write_probe_record(campaign)
    assert live.host_probe_problem(campaign) is None
    for unclean in (["1/HP-09"], None):
        path = campaign / "coordinator" / live.HOST_PROBE_DIR / str(record["probe_run"] + 1) / "result.json"
        path.parent.mkdir()
        body = {**record, "probe_run": record["probe_run"] + 1}
        if unclean is None:
            body.pop("unclean_launches")                          # a record from before the check: refused
        else:
            body["unclean_launches"] = unclean
        canonical.write_once(path, runner._pretty(body))
        assert "census is unclean or unrecorded" in live.host_probe_problem(campaign)
        record = body


@needs_sandbox
def test_run_refuses_to_launch_over_an_unclean_probe_launch(lab, monkeypatch):
    def unclean(patch, campaign):
        patch.setattr(live, "census_lost_probes", lambda d: [{"launch": "1/HP-09", "census": {"complete": False}}])
    with pytest.raises(ContractError, match=r"probe launches \['1/HP-09'\] left survivors"):
        scenario(lab, "smoke-unclean-probe", {}, before_run=unclean)
    campaign = lab.store / "synthetic" / "smoke-unclean-probe"
    assert all(not journal_of(campaign, r["run_id"]) for r in runs_of(campaign))


def test_host_probe_installs_the_live_signal_handlers(tmp_path, monkeypatch, capsys):
    installed = []
    monkeypatch.setenv("RAVEL_EVAL_LIVE", "1")
    monkeypatch.setattr(cli, "install_live_handlers", lambda: installed.append(True))
    monkeypatch.setattr(live, "host_probe", lambda campaign, **kw: {"ok": True, "SYNTHETIC": kw})
    assert cli.main(["host-probe", "--campaign", str(tmp_path), "--dry-start"]) == 0
    assert installed == [True] and json.loads(capsys.readouterr().out)["SYNTHETIC"]["dry_start"] is True


# ---------------------------------------------------------------- the leader wait is bounded (E-97)

def test_a_leader_that_outlives_the_kill_is_a_survivor_and_never_waited_on_forever(tmp_path, monkeypatch):
    base = Path(os.path.realpath(tmp_path))
    monkeypatch.setattr(isolation, "_terminate", lambda proc, watch, grace: None)   # SYNTHETIC: the kill has no effect
    monkeypatch.setattr(isolation, "LEADER_WAIT_S", 0.5)
    monkeypatch.setattr(isolation, "CENSUS_WAIT_S", 0.3)
    recorded, started = [], time.monotonic()
    try:
        result = isolation.launch(["/bin/sleep", "30"], cwd=str(base), env={}, profile=None, timeout_s=0.5,
                                  stdout_path=str(base / "o"), stderr_path=str(base / "e"), on_start=recorded.append)
        assert result.timed_out is True and result.exit_code is None and recorded[0]["pid"] in result.survivors
        assert time.monotonic() - started < 20
    finally:
        pid = recorded[0]["pid"] if recorded else None
        if pid is not None and isolation._start_time(pid) is not None:
            os.kill(pid, signal.SIGKILL)   # this test's own child, by its exact pid
            os.waitpid(pid, 0)


# ================================================================ the paid smoke's findings (E-162)

# ---------------------------------------------------------------- the denial collector and the log tool (LC-18)

UNIFIED_LOG = Path(__file__).parent / "fixtures" / "unified_log"


def recorded_log(*names):
    """Recorded ``log show --style ndjson`` output from this macOS 15.5 host (2026-09-27), each file ending with the
    tool's own count trailer: ``log_show_self_invocation.ndjson`` is the one line the smoke's run-1 window held (the
    collector's own ``log`` invocation, whose arguments quote the predicate and so the subject marker);
    ``sandbox_deny.ndjson`` is a Seatbelt deny report of a system daemon. The host's boot UUID is replaced by zeros
    in both; every other field is as recorded."""
    return b"".join((UNIFIED_LOG / name).read_bytes() for name in names)


def fake_log_show(monkeypatch, stdout):
    """``log show`` answers with ``stdout`` (exit 0); the call is recorded, never run."""
    calls = []

    def run(argv, **kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(live.subprocess, "run", run)
    return calls


def log_events(data):
    return [json.loads(line) for line in data.splitlines() if b'"eventMessage"' in line]


def test_the_recorded_self_invocation_matched_the_former_predicate():
    """The fixture is the smoke's LC-18 count of 1: the log tool's own record, sent by the log tool itself, carrying
    the subject marker only because its arguments quote the predicate; the profile's deny-default message is that
    marker."""
    [event] = log_events(recorded_log("log_show_self_invocation.ndjson"))
    assert event["processImagePath"] == event["senderImagePath"] == live.LOG
    assert event["subsystem"] == "com.apple.log" and live.SUBJECT_MARKER in event["eventMessage"]
    assert "'--predicate' 'eventMessage CONTAINS \"ravel-subject\"" in event["eventMessage"]
    profile = isolation.seatbelt_profile(isolation.SandboxPolicy(read_roots=(os.path.realpath(sys.base_prefix),)))
    assert f'(deny default (with message "{live.SUBJECT_MARKER}"))' in profile.splitlines()


def test_the_denial_collector_never_counts_its_own_log_invocation(monkeypatch):
    calls = fake_log_show(monkeypatch, recorded_log("log_show_self_invocation.ndjson"))
    found = live.sandbox_denials("2026-09-27T17:43:27Z", "2026-09-27T17:46:49Z")
    assert found == {"available": True, "count": 0, "truncated": False, "error": None, "processes": {}}
    [argv] = calls
    predicate = argv[argv.index("--predicate") + 1]
    assert predicate == live.DENIAL_PREDICATE and predicate.startswith('sender == "Sandbox" AND (')
    assert live.PID_DENIAL_PREDICATE.startswith('sender == "Sandbox" AND ')


def test_a_line_carrying_the_marker_counts_only_from_the_sandbox_sender(monkeypatch):
    [event] = log_events(recorded_log("log_show_self_invocation.ndjson"))
    others = []
    for process, sender in (("/bin/zsh", "/bin/zsh"), ("/usr/bin/log", "/usr/lib/libSystem.B.dylib"),
                            ("/kernel", "/usr/bin/log")):
        others.append(json.dumps({**event, "processImagePath": process, "senderImagePath": sender}).encode())
    fake_log_show(monkeypatch, b"\n".join(others) + b"\n")
    assert live.sandbox_denials("2026-09-27T17:43:27Z", "2026-09-27T17:46:49Z")["count"] == 0


def test_the_denial_collector_counts_a_real_sandbox_deny_line(monkeypatch):
    data = recorded_log("sandbox_deny.ndjson", "log_show_self_invocation.ndjson")
    [deny, _] = log_events(data)
    assert deny["senderImagePath"].endswith("/Sandbox") and "logd_helper(3462) deny(1)" in deny["eventMessage"]
    fake_log_show(monkeypatch, data)
    found = live.sandbox_denials("2026-09-27T18:29:00Z", "2026-09-27T18:31:00Z")
    assert found == {"available": True, "count": 1, "truncated": False, "error": None,
                     "processes": {"logd_helper": 1}}
    assert live.sandbox_denials("2026-09-27T18:29:00Z", "2026-09-27T18:31:00Z", pid=3462)["count"] == 1
    assert live.sandbox_denials("2026-09-27T18:29:00Z", "2026-09-27T18:31:00Z", pid=346)["count"] == 0


def test_a_deny_line_from_the_log_tool_or_another_sender_is_not_a_denial(monkeypatch):
    [deny] = log_events(recorded_log("sandbox_deny.ndjson"))
    mutated = [{**deny, "processImagePath": live.LOG}, {**deny, "senderImagePath": live.LOG},
               {**deny, "senderImagePath": "/usr/lib/system/libsystem_trace.dylib"}]
    fake_log_show(monkeypatch, b"".join(json.dumps(m).encode() + b"\n" for m in mutated) + b"{\"eventMessage\": 1}\n")
    assert live.sandbox_denials("2026-09-27T18:29:00Z", "2026-09-27T18:31:00Z")["count"] == 0
