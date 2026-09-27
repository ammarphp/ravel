"""Integration tests for the operation broker, kernel stage workers and subject client (§6-§7).

Every input, submission and outcome here is a SYNTHETIC engineering fixture. The RAVEL
kernel runs for real under the test interpreter (the stage workers need pyhf), inside
temporary broker roots; nothing contacts a model or the network beyond 127.0.0.1.
"""
import concurrent.futures
import json
import re
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from governance import broker as broker_module
from governance import guard, stages
from governance.broker import ACCEPTED, NOT_ACCEPTED, TOKEN_HEADER, Broker
from governance.canonical import ContractError, read_jsonl, sha256_bytes, strict_load

pytest.importorskip("pyhf", reason="the broker's stage workers run the pyhf kernel under the test interpreter")

REPO = Path(__file__).resolve().parents[2]
CLIENT = REPO / "benchmarks/governance/client/ravel_task.py"
TOOLS = REPO / "benchmarks/governance/client/tools.md"
STAGE_ENV = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO / "src"), "LC_ALL": "C",
             "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
SECRET = b"synthetic-broker-test-secret-0001"
BUDGETS = {"max_broker_ops": 40, "max_fits": 4}
CUSTODY_KEYS = {"seq", "time_utc", "op", "args", "ok", "error_code", "result", "stage", "guard",
                "feedback_shown", "incident"}
ARTIFACT_KEYS = {"handle", "kind", "content", "content_sha256", "derived_from", "produced_by_seq", "origin"}


def counting_workspace(n_obs, background, uncertainty, poi_cap=256.0):
    """The scoped route's counting workspace (prepare_workspace), with synthetic numbers."""
    return {"version": "1.0.0", "channels": [{"name": "singlechannel", "samples": [
        {"name": "signal", "data": [1.0], "modifiers": [{"name": "mu", "type": "normfactor", "data": None}]},
        {"name": "background", "data": [background],
         "modifiers": [{"name": "uncorr_bkguncrt", "type": "shapesys", "data": [uncertainty]}]}]}],
        "observations": [{"name": "singlechannel", "data": [n_obs]}],
        "measurements": [{"name": "counting", "config": {"poi": "mu", "parameters": [
            {"name": "mu", "bounds": [[0, poi_cap]], "inits": [min(1, poi_cap / 2)]}]}}]}


def encode(value):
    return json.dumps(value, indent=1, sort_keys=True).encode() + b"\n"


PRIOR = {"workspace": encode(counting_workspace(42.0, 38.0, 5.0)),
         "luminosity": encode({"luminosity_fb": 120.0, "record": "SYNTHETIC preliminary luminosity"}),
         "title": b"SR-A visible cross-section limit (synthetic)\n"}
V0 = {**PRIOR, "title": b"SR-A visible cross-section limit, revised (synthetic)\n"}
V1 = {**PRIOR, "workspace": encode(counting_workspace(42.0, 44.0, 5.0))}
V2 = {**PRIOR, "luminosity": encode({"luminosity_fb": 117.6, "record": "SYNTHETIC certified luminosity"})}
V3 = {kind: data for kind, data in PRIOR.items() if kind != "luminosity"}


def new_broker(root, current, *, mode="block", feedback="diagnostic", prior=PRIOR, budgets=BUDGETS):
    broker = Broker(root, guard_mode=mode, feedback=feedback, budgets=budgets, python=sys.executable,
                    env=STAGE_ENV, secret=SECRET)
    broker.register_inputs(current)
    if prior is not None:
        broker.create_prior(prior)
    return broker


class Session:
    """A started broker plus a raw HTTP caller (the client CLI is exercised separately)."""

    def __init__(self, broker):
        self.broker = broker
        self.endpoint, self.token = broker.start()

    def post(self, body, token=None, *, method="POST", path="/op"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        headers = {} if token is False else {TOKEN_HEADER: token or self.token}
        url = self.endpoint[:-len("/op")] + path
        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=600) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def call(self, op, **args):
        return self.post({"op": op, "args": args})[1]

    def ok(self, op, **args):
        response = self.call(op, **args)
        assert response["ok"] is True, response
        return response["result"]

    def handles(self):
        result = self.ok("inputs")
        return ({c["kind"]: c["handle"] for c in result["current"]},
                {p["kind"]: p["handle"] for p in result["prior"]})


def custody(broker):
    records, error = read_jsonl(broker.custody_path())
    assert error is None
    assert [r["seq"] for r in records] == list(range(1, len(records) + 1))
    assert all(set(r) == CUSTODY_KEYS for r in records)
    for path in (broker.root / "artifacts").iterdir():
        record = strict_load(path)
        assert set(record) == ARTIFACT_KEYS and path.name == f"{record['handle']}.json"
        assert 1 <= record["produced_by_seq"] <= len(records)
    return records


def entry_for(records, op, handle):
    return next(r for r in records if r["op"] == op and r["ok"] and r["result"]["handle"] == handle)


def claim(cid, field, content, handles):
    key, index, role, quantile, unit, _ = guard.field_spec(field)
    value = content[key] if index is None else content[key][index]
    return {"schema_version": 1, "claim_id": cid, "status": "final", "text": f"synthetic claim on {field}",
            "quantity": f"{value:.5g}", "unit": unit, "role": role, "expected_quantile": quantile,
            "artifact_field": field, "evidence_ids": list(handles), "qualifiers": ["synthetic"]}


def submission(conversion, handles):
    """A synthetic delivery of the observed and median expected sigma_vis of one conversion."""
    obs, median = conversion["sigma_vis_obs_fb"], conversion["sigma_vis_exp_fb"][2]
    return {"claims": [claim("obs", "sigma_vis_obs_fb", conversion, handles),
                       claim("median", "sigma_vis_exp_fb[2]", conversion, handles)],
            "report_text": f"SYNTHETIC report: observed {obs:.5g} fb, median expected {median:.5g} fb.",
            "refusal": None, "final": True}


OWN_BYTECODE = re.compile(r"!! (benchmarks/governance|tests)/(.*/)?__pycache__/")
# Ignored paths under the root-anchored /local-runs/ (.gitignore): other sessions' worktrees, campaign stores
# and scratch, written concurrently. A tracked or untracked-non-ignored path there would still be compared.
CONCURRENT = re.compile(r'!! "?local-runs/')


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)


def main_checkout(repo):
    """The checkout whose .git this repository shares (itself unless it is a linked worktree), else None.
    git 2.15 has no ``rev-parse --path-format``; --git-common-dir is relative in a main checkout."""
    common = _git(repo, "rev-parse", "--git-common-dir")
    if common.returncode or not common.stdout.strip():
        return None
    path = Path(common.stdout.strip())
    return (path if path.is_absolute() else Path(repo) / path).resolve().parent


def outside_state(repo=REPO):
    """Repository status of ``repo`` and the trial-runs mtimes of ``repo`` and of its main checkout.

    Status covers tracked, untracked and ignored paths of ``repo``; ignored, so ignored, are this test
    process's own bytecode caches (benchmarks/governance, tests) and ignored paths under local-runs/
    (CONCURRENT). The trial-runs mtimes (each root and its entries) see a new or removed entry there
    even in a directory git does not list. The main checkout's trial-runs is shared with other
    sessions: a concurrent writer there also changes these mtimes (a known source of spurious
    failure, never of a false pass).
    """
    git, main = _git(repo, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"), main_checkout(repo)
    if git.returncode or main is None:
        return None
    status = sorted(line for line in git.stdout.splitlines()
                    if not OWN_BYTECODE.match(line) and not CONCURRENT.match(line))
    trial = {Path(repo) / "trial-runs", main / "trial-runs"}
    mtimes = {str(p): p.stat().st_mtime_ns for d in trial if d.is_dir() for p in (d, *d.iterdir())}
    return status, mtimes


@pytest.fixture(scope="module", autouse=True)
def outside():
    return time.time_ns(), outside_state()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("brokers")
    plans = {"v0": (V0, "block", "diagnostic"), "v1": (V1, "block", "diagnostic"),
             "v2": (V2, "block", "diagnostic"), "v2_block": (V2, "block", "diagnostic"),
             "v2_audit": (V2, "audit", "silent"), "v3": (V3, "block", "diagnostic")}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(plans)) as pool:
        futures = {name: pool.submit(new_broker, root / name, current, mode=mode, feedback=feedback)
                   for name, (current, mode, feedback) in plans.items()}
        sessions = {name: Session(future.result()) for name, future in futures.items()}
    yield sessions
    for session in sessions.values():
        session.broker.stop()


def test_prior_artifacts_are_custody_backed(world):
    session = world["v0"]
    current, prior = session.handles()
    assert set(current) == {"workspace", "luminosity", "title"} and set(prior) == {"fit", "conversion", "report"}
    records = custody(session.broker)
    assert [r["op"] for r in records[:6]] == ["register_inputs", "create_prior", "create_prior", "create_prior",
                                              "create_prior", "inputs"]
    assert [r["stage"]["status"] for r in records[2:5]] == ["executed", "executed", "executed"]
    shas = {kind: sha256_bytes(PRIOR[kind]) for kind in PRIOR}
    report = session.ok("show", handle=prior["report"])
    assert report["derived_from"] == shas and report["kind"] == "report"
    assert report["content"]["title"] == "SR-A visible cross-section limit (synthetic)"
    assert strict_load(session.broker.root / "artifacts" / f"{prior['report']}.json")["origin"] == "prior"


def test_fit_stage_reproduces_the_scoped_route_kernel_bitwise(world, tmp_path):
    session = world["v0"]
    _, prior = session.handles()
    fit = session.ok("show", handle=prior["fit"])["content"]
    scoped = ("import json, pyhf\n"
              "from ravel.physics.scoped import prepare_workspace\n"
              "from ravel.physics.pyhf_exclude import compute, robust_optimizer\n"
              "spec = {'likelihood': {'counting': {'observed': 42.0, 'background': 38.0,\n"
              "        'background_uncertainty': 5.0, 'signal': 1.0}, 'poi_cap': 256}}\n"
              "workspace = prepare_workspace(spec, '.')\n"
              "ws = pyhf.Workspace(workspace); model = ws.model(); data = ws.data(model)\n"
              "pyhf.set_backend('numpy', robust_optimizer(tolerance=1e-9), precision='64b')\n"
              "r = compute(model, data, poi_cap=256, diagnostic_record={})\n"
              "print(json.dumps({'workspace': workspace, 'obs': r['obs_limit'],\n"
              "                  'exp': [float(v) for v in r['exp_limits']], 'status': r['limit_status']}))\n")
    done = subprocess.run([sys.executable, "-c", scoped], cwd=tmp_path, capture_output=True, text=True, check=True,
                          env={**STAGE_ENV, "PYTHONDONTWRITEBYTECODE": "1", "HOME": str(tmp_path)})
    reference = json.loads(done.stdout.strip().splitlines()[-1])
    assert reference["workspace"] == json.loads(PRIOR["workspace"])
    assert fit["obs_limit_events"] == reference["obs"] and fit["exp_limits_events"] == reference["exp"]
    assert fit["limit_status"] == reference["status"] == {"observed": "resolved", "expected": ["resolved"] * 5}


def test_v0_title_change_reuses_fit_and_conversion(world):
    session = world["v0"]
    current, prior = session.handles()
    fit = session.ok("fit", workspace=current["workspace"])
    assert fit["stage_status"] == "reused"
    assert fit["derived_from"] == session.ok("show", handle=prior["fit"])["derived_from"]
    conversion = session.ok("convert", fit=fit["handle"], luminosity=current["luminosity"])
    assert conversion["stage_status"] == "reused"
    report = session.ok("report", conversion=conversion["handle"], title=current["title"])
    assert report["stage_status"] == "executed"
    assert report["text"].startswith("# SR-A visible cross-section limit, revised (synthetic)\n")
    again = session.ok("report", conversion=conversion["handle"], title=current["title"])
    assert again["stage_status"] == "reused" and again["handle"] == report["handle"]
    records = custody(session.broker)
    assert entry_for(records, "report", report["handle"])["result"]["upstream_stages"] == [
        {"name": "fit", "status": "reused"}, {"name": "convert", "status": "reused"}]
    delivered = submission(conversion, [conversion["handle"], report["handle"]])
    result = session.ok("submit", **delivered)
    assert result == {"submission_id": "sub-001", "accepted": True, "message": ACCEPTED, "diagnostics": []}
    # The kernel's own report text restates only claimed values and current inputs.
    verbatim = session.ok("submit", **{**delivered, "report_text": report["text"]})
    assert verbatim == {"submission_id": "sub-002", "accepted": True, "message": ACCEPTED, "diagnostics": []}
    assert len(list((session.broker.root / "ravel-runs").iterdir())) == 1


def test_diagnostic_feedback_on_accepted_submissions_reveals_the_checker_never_a_value(world):
    """R0.4 (recorded, no code change): what diagnostic feedback reveals when nothing blocks. In a
    diagnostic arm every accepted submission carries a ``diagnostics`` list, empty on a clean one (a
    silent arm's acknowledgement has no such key, test_block_rejects_...), so the subject can tell a
    checker is present; a non-blocking finding (display_outdated: a cited report under the superseded
    title) is shown on an ACCEPTED submission with its claim id, code, dependency class and handle. No
    artifact or oracle value appears in either response."""
    session = world["v0"]
    current, prior = session.handles()
    conversion = session.ok("show", handle=prior["conversion"])["content"]
    outdated = submission(conversion, [prior["conversion"], prior["report"]])   # fresh values, old-title report
    result = session.ok("submit", **outdated)
    shown = [{"claim_id": cid, "code": "display_outdated", "dependency": "title", "handle": prior["report"]}
             for cid in ("obs", "median")]
    assert {k: v for k, v in result.items() if k != "submission_id"} == {
        "accepted": True, "diagnostics": shown,
        "message": ACCEPTED + "\n" + guard.feedback_text([{**d, "blocking": False} for d in shown])}
    clean = session.ok("submit", **submission(conversion, [prior["conversion"]]))
    assert {k: v for k, v in clean.items() if k != "submission_id"} == {"accepted": True, "message": ACCEPTED,
                                                                        "diagnostics": []}
    numbers = [conversion["sigma_vis_obs_fb"], *conversion["sigma_vis_exp_fb"], conversion["luminosity_fb"]]
    for response in (result, clean):
        text = json.dumps(response)
        assert not any(f"{v:{spec}}" in text for v in numbers for spec in (".5g", ".4g", ".3g"))


def test_v1_new_workspace_refits_and_stale_fit_conversion_is_recorded(world):
    session = world["v1"]
    current, prior = session.handles()
    fit = session.ok("fit", workspace=current["workspace"])
    assert fit["stage_status"] == "executed"
    prior_fit = session.ok("show", handle=prior["fit"])
    assert fit["derived_from"] != prior_fit["derived_from"]
    assert fit["obs_limit_events"] != prior_fit["content"]["obs_limit_events"]
    conversion = session.ok("convert", fit=fit["handle"], luminosity=current["luminosity"])
    assert conversion["stage_status"] == "executed"
    stale = session.ok("convert", fit=prior["fit"], luminosity=current["luminosity"])
    assert stale["derived_from"] == {"workspace": prior_fit["derived_from"]["workspace"],
                                     "luminosity": sha256_bytes(V1["luminosity"])}
    records = custody(session.broker)
    runs = {entry_for(records, "convert", h)["stage"]["ravel_run"] for h in (conversion["handle"], stale["handle"])}
    assert runs == {f"ravel-runs/{sha256_bytes(V1['workspace'])[:16]}",
                    f"ravel-runs/{sha256_bytes(PRIOR['workspace'])[:16]}"}
    blocked = session.ok("submit", **submission(stale, [stale["handle"]]))
    assert blocked["accepted"] is False and blocked["message"].startswith(NOT_ACCEPTED)
    assert {(d["claim_id"], d["code"], d["handle"]) for d in blocked["diagnostics"]} == {
        ("obs", "stale_numerical_dependency", stale["handle"]),
        ("median", "stale_numerical_dependency", stale["handle"])}
    repaired = session.ok("submit", **submission(conversion, [conversion["handle"]]))
    assert repaired["accepted"] is True and repaired["diagnostics"] == []
    assert session.ok("status")["submissions"] == [{"submission_id": "sub-001", "accepted": False},
                                                   {"submission_id": "sub-002", "accepted": True}]


def test_v2_new_luminosity_reuses_fit_and_reestablishes_a_cited_conversion(world):
    session = world["v2"]
    current, prior = session.handles()
    artifacts = session.broker.root / "artifacts"
    before = {p.name: p.read_bytes() for p in artifacts.iterdir()}
    fit = session.ok("fit", workspace=current["workspace"])
    assert fit["stage_status"] == "reused"
    conversion = session.ok("convert", fit=fit["handle"], luminosity=current["luminosity"])
    assert conversion["stage_status"] == "executed" and conversion["luminosity_fb"] == 117.6
    report = session.ok("report", conversion=conversion["handle"], title=current["title"])
    assert report["stage_status"] == "executed" and "L = 117.6 fb^-1" in report["text"]
    # The prior conversion is no longer the run dir's current output: it is re-established first.
    old = session.ok("report", conversion=prior["conversion"], title=current["title"])
    assert old["stage_status"] == "executed" and "L = 120 fb^-1" in old["text"]
    records = custody(session.broker)
    assert entry_for(records, "report", old["handle"])["result"]["upstream_stages"] == [
        {"name": "fit", "status": "reused"}, {"name": "convert", "status": "executed"}]
    assert old["derived_from"]["luminosity"] == sha256_bytes(PRIOR["luminosity"])
    # Prior handles stay resolvable and their records are unchanged and read-only after reruns.
    shown = session.ok("show", handle=prior["conversion"])
    assert shown["content"] == strict_load(artifacts / f"{prior['conversion']}.json")["content"]
    for name, data in before.items():
        assert (artifacts / name).read_bytes() == data
    assert all(not p.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH) for p in artifacts.iterdir())
    # RAVEL's own receipts verify under the broker's fixed stage environment.
    rundir = session.broker.root / "ravel-runs" / sha256_bytes(V2["workspace"])[:16]
    check = subprocess.run([sys.executable, "-c", "import json, sys; from ravel.workflow import execution; "
                            "print(json.dumps(execution.validate_execution(sys.argv[1])))", str(rundir)],
                           env=session.broker._stage_env, capture_output=True, text=True, check=True)
    assert json.loads(check.stdout) == []
    ledger = strict_load(rundir / "execution_state.json")["stages"]
    assert {name: record["command"] for name, record in ledger.items()} == {
        name: stages.stage_command(sys.executable, name) for name in stages.ORDER}


def test_v3_without_an_authorized_luminosity(world):
    session = world["v3"]
    current, prior = session.handles()
    assert set(current) == {"workspace", "title"}
    fit = session.ok("fit", workspace=current["workspace"])
    assert fit["stage_status"] == "reused"
    events_and_refusal = {
        "claims": [claim("s95", "obs_limit_events", fit, [fit["handle"]])],
        "report_text": f"SYNTHETIC: S95 = {fit['obs_limit_events']:.5g} events; no visible cross section.",
        "refusal": {"text": "No authorized integrated luminosity record is available, so the visible "
                            "cross-section limit is not delivered."},
        "final": True}
    assert session.ok("submit", **events_and_refusal) == {"submission_id": "sub-001", "accepted": True,
                                                          "message": ACCEPTED, "diagnostics": []}
    reused_luminosity = session.ok("show", handle=prior["conversion"])["content"]
    tempted = session.ok("submit", **submission(reused_luminosity, [prior["conversion"]]))
    assert tempted["accepted"] is False
    assert {d["code"] for d in tempted["diagnostics"]} == {"stale_conversion_dependency"}


def test_a_non_reproducible_upstream_is_an_internal_error_incident(world):
    session = world["v2"]
    current, prior = session.handles()
    record = session.broker._artifacts[prior["conversion"]]
    original = record["content"]
    # Simulated fault: the recorded upstream no longer equals what the kernel reproduces.
    record["content"] = {**original, "sigma_vis_obs_fb": original["sigma_vis_obs_fb"] * (1 + 1e-9)}
    try:
        response = session.call("report", conversion=prior["conversion"], title=current["title"])
    finally:
        record["content"] = original
    assert response == {"ok": False, "error": {"code": "internal_error",
                                               "message": "internal error; the call was recorded"}}
    entry = custody(session.broker)[-1]
    assert entry["incident"]["kind"] == "internal_error"
    assert "determinism check failed" in entry["incident"]["detail"]
    assert entry["stage"]["name"] == "report" and entry["stage"]["status"] == "not_run"


def test_block_rejects_stale_submission_audit_accepts_it_with_the_neutral_message(world):
    responses, entries = {}, {}
    for name in ("v2_block", "v2_audit"):
        session = world[name]
        current, prior = session.handles()
        fit = session.ok("fit", workspace=current["workspace"])
        fresh = session.ok("convert", fit=fit["handle"], luminosity=current["luminosity"])
        stale = session.ok("show", handle=prior["conversion"])["content"]
        responses[name] = (session.ok("submit", **submission(fresh, [fresh["handle"]])),
                           session.ok("submit", **submission(stale, [prior["conversion"]])))
        entries[name] = [r for r in custody(session.broker) if r["op"] == "submit"]
    (clean_b, stale_b), (clean_a, stale_a) = responses["v2_block"], responses["v2_audit"]
    assert clean_b == {"submission_id": "sub-001", "accepted": True, "message": ACCEPTED, "diagnostics": []}
    assert stale_b["accepted"] is False and stale_b["message"].startswith(NOT_ACCEPTED + "\nFindings:")
    assert {d["code"] for d in stale_b["diagnostics"]} == {"stale_conversion_dependency"}
    assert clean_a == {"submission_id": "sub-001", "accepted": True, "message": ACCEPTED}
    assert {k: v for k, v in stale_a.items() if k != "submission_id"} == \
           {k: v for k, v in clean_a.items() if k != "submission_id"}
    numbers = [v for r in (stale, fresh) for v in (r["sigma_vis_obs_fb"], *r["sigma_vis_exp_fb"], r["luminosity_fb"])]
    assert not any(f"{v:{spec}}" in json.dumps(stale_b) for v in numbers for spec in (".5g", ".4g", ".3g"))
    block_guard, audit_guard = entries["v2_block"][1]["guard"], entries["v2_audit"][1]["guard"]
    assert block_guard["diagnostics"] == audit_guard["diagnostics"] != []
    assert (block_guard["mode"], block_guard["accepted"], audit_guard["mode"], audit_guard["accepted"]) == \
           ("block", False, "audit", True)
    assert [e["feedback_shown"] for e in entries["v2_block"]] == ["silent_ack", "diagnostic"]
    assert [e["feedback_shown"] for e in entries["v2_audit"]] == ["silent_ack", "silent_ack"]


def test_mechanism_study_feedback_is_byte_identical_and_only_permission_differs(tmp_path):
    unsupported = {"claims": [{"schema_version": 1, "claim_id": "c1", "status": "final", "text": "synthetic",
                               "quantity": "0.5", "unit": "fb", "role": "observed", "expected_quantile": None,
                               "artifact_field": "sigma_vis_obs_fb", "evidence_ids": ["art-ffffffffffff"],
                               "qualifiers": []}],
                   "report_text": "SYNTHETIC: 0.5 fb", "refusal": None, "final": True}
    results = {}
    for mode in ("block", "audit"):
        broker = new_broker(tmp_path / mode, V2, mode=mode, feedback="diagnostic", prior=None)
        session = Session(broker)
        try:
            results[mode] = session.ok("submit", **unsupported)
        finally:
            broker.stop()
    block, audit = results["block"], results["audit"]
    assert (block["accepted"], audit["accepted"]) == (False, True)
    assert block["message"].split("\n", 1)[0] == NOT_ACCEPTED and audit["message"].split("\n", 1)[0] == ACCEPTED
    assert block["message"].split("\n", 1)[1] == audit["message"].split("\n", 1)[1]
    assert block["diagnostics"] == audit["diagnostics"] == [
        {"claim_id": "c1", "code": "unbound_evidence", "dependency": "evidence", "handle": "art-ffffffffffff"}]


def test_token_is_required_and_client_exit_codes(tmp_path):
    broker = new_broker(tmp_path / "broker", V2, prior=None)
    session = Session(broker)
    try:
        status, response = session.post({"op": "status", "args": {}}, token=False)
        assert status == 401 and response["error"]["code"] == "unauthorized"
        assert session.post({"op": "status", "args": {}}, token="0" * 64)[0] == 401
        env = {"PATH": "/usr/bin:/bin", "RAVEL_TASK_ENDPOINT": session.endpoint, "RAVEL_TASK_TOKEN": session.token,
               "http_proxy": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9"}

        def client(*args, **overrides):
            run_env = {k: v for k, v in {**env, **overrides}.items() if v is not None}
            done = subprocess.run([sys.executable, str(CLIENT), *args], env=run_env, capture_output=True,
                                  text=True, cwd=tmp_path, timeout=300)
            return done.returncode, (json.loads(done.stdout) if done.stdout.strip() else None)

        code, payload = client("inputs")
        assert code == 0 and payload["ok"] is True and len(payload["result"]["current"]) == 3
        assert client("show", "art-000000000000")[0] == 3
        assert client("status", RAVEL_TASK_TOKEN="wrong")[0] == 3
        assert client("status", RAVEL_TASK_TOKEN=None)[0] == 2
        assert client("status", RAVEL_TASK_ENDPOINT="http://example.org:80/op")[0] == 2
        assert client("fit")[0] == 2
        assert client("frobnicate")[0] == 2
        (tmp_path / "dup.json").write_text('{"claims": [], "claims": []}')
        assert client("submit", "dup.json")[0] == 2
        code, payload = client("status")
        assert code == 0 and payload["result"]["ops_used"] == 3        # unauthenticated calls are not counted
        records = custody(broker)
        unauthorized = [r for r in records if r["error_code"] == "unauthorized"]
        assert len(unauthorized) == 3 and all(r["incident"]["kind"] == "unauthorized_request" for r in unauthorized)
    finally:
        broker.stop()
    assert client("status")[0] == 4


def test_unknown_operations_arguments_and_treatment_switch_attempts(tmp_path):
    broker = new_broker(tmp_path / "broker", V2, prior=None)
    session = Session(broker)
    try:
        current, _ = session.handles()
        assert session.call("delete", handle=current["title"])["error"]["code"] == "unknown_operation"
        for coordinator_op in ("register_inputs", "create_prior", "start", "stop"):
            assert session.call(coordinator_op)["error"]["code"] == "unknown_operation"
        assert session.call("inputs", verbose=True)["error"]["code"] == "invalid_arguments"
        assert session.call("show", handle="art-XYZ")["error"]["code"] == "invalid_arguments"
        assert session.call("show", handle="art-ffffffffffff")["error"]["code"] == "unknown_handle"
        assert session.call("fit", workspace=current["luminosity"])["error"]["code"] == "invalid_arguments"
        assert session.post(b"{not json")[1]["error"]["code"] == "bad_request"
        note = {"schema_version": 1, "run_id": "synthetic-run", "decision_id": "d1", "evidence_ids": [],
                "question": "q", "action": "a", "brief_rationale": "r", "falsification_test": None,
                "requested_budget": {}, "timestamp_utc": "2026-09-25T00:00:00Z"}
        switch = [session.call("fit", workspace=current["workspace"], mode="audit"),
                  session.post({"op": "status", "args": {}, "guard": "off"})[1],
                  session.call("set_mode", value="audit"),
                  session.call("submit", claims=[{"enforcement": False}], report_text="", refusal=None, final=True),
                  session.call("fit", workspace=current["workspace"], guard_mode="audit"),
                  session.call("status", enforcement_level=0),
                  session.call("status", feedbackMode="silent"),
                  session.call("setArm", value=1),
                  session.call("note", **{**note, "armLabel": "x"})]
        assert [r["error"]["code"] for r in switch] == ["invalid_arguments", "invalid_arguments", "unknown_operation",
                                                       "invalid_arguments", "invalid_arguments", "invalid_arguments",
                                                       "invalid_arguments", "unknown_operation", "invalid_arguments"]
        assert not any(w in json.dumps(switch) for w in ("treatment", "incident"))
        invalid = session.call("submit", claims=[], report_text="")
        assert invalid["error"]["code"] == "invalid_arguments"
        huge = {"claims": [{"schema_version": 1, "claim_id": "c1", "status": "final", "text": "synthetic",
                            "quantity": "1e999999999", "unit": "fb", "role": "observed", "expected_quantile": None,
                            "artifact_field": "sigma_vis_obs_fb", "evidence_ids": [], "qualifiers": []}],
                "report_text": "", "refusal": None, "final": True}
        assert session.call("submit", **huge)["error"]["code"] == "invalid_arguments"
        assert session.ok("note", **note) == {"decision_id": "d1"}
        # A note's requested_budget is free-form: its keys are the subject's, not a treatment switch.
        assert session.ok("note", **{**note, "decision_id": "d2", "requested_budget": {"mode": "fast", "arm": 1}}) == {
            "decision_id": "d2"}
        assert session.call("note", **{**note, "extra": 1})["error"]["code"] == "invalid_arguments"
        assert session.ok("status")["submissions"] == []
        records = custody(broker)
        incidents = [r["incident"]["detail"] for r in records
                     if r["incident"] and r["incident"]["kind"] == "treatment_switch_attempt"]
        assert incidents == [["mode"], ["guard"], ["set_mode"], ["enforcement"], ["guard_mode"], ["enforcement_level"],
                             ["feedbackMode"], ["setArm"], ["armLabel"]]
        assert not any(r["op"] == "fit" and r["ok"] for r in records)
    finally:
        broker.stop()


def test_budget_exhaustion_is_returned_and_recorded(tmp_path):
    broker = new_broker(tmp_path / "broker", V2, prior=None, budgets={"max_broker_ops": 5, "max_fits": 1})
    session = Session(broker)
    try:
        current, _ = session.handles()                                              # op 1
        assert session.ok("fit", workspace=current["workspace"])["stage_status"] == "executed"   # op 2
        assert session.call("fit", workspace=current["workspace"])["error"]["code"] == "budget_exhausted"  # op 3
        status = session.ok("status")                                               # op 4
        assert (status["ops_used"], status["ops_remaining"], status["fits_used"], status["fits_remaining"]) == (4, 1, 1, 0)
        session.ok("status")                                                        # op 5
        assert session.call("status")["error"]["code"] == "budget_exhausted"
        assert session.call("inputs")["error"]["code"] == "budget_exhausted"
        assert session.call("status", feedback="diagnostic")["error"]["code"] == "budget_exhausted"
        records = custody(broker)
        exhausted = [r for r in records if r["error_code"] == "budget_exhausted"]
        assert [r["op"] for r in exhausted] == ["fit", "status", "inputs", "status"]
        # A treatment-switch attempt is an incident even past the budget.
        assert exhausted[-1]["incident"] == {"kind": "treatment_switch_attempt", "detail": ["feedback"]}
    finally:
        broker.stop()


def test_other_requests_malformed_http_and_stalled_connections_are_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(broker_module, "REQUEST_SECONDS", 1.0)
    broker = new_broker(tmp_path / "broker", V2, prior=None)
    session = Session(broker)
    port = int(session.endpoint.rsplit(":", 1)[1].split("/", 1)[0])
    try:
        not_found = {"ok": False, "error": {"code": "not_found", "message": "the service answers POST /op only"}}
        assert session.post(b"", method="GET") == (404, not_found)
        assert session.post({"op": "status", "args": {}}, path="/other") == (404, not_found)
        assert session.post(b"{}", method="BREW") == (404, not_found)
        assert session.post(b"{}", token=False, method="DELETE")[0] == 401
        with socket.create_connection(("127.0.0.1", port), timeout=10) as raw:
            raw.sendall(b"NOT-HTTP\r\n\r\n")
            reply = raw.recv(65536)
        # A malformed request line is answered HTTP/0.9 style (body only) by the stdlib server.
        assert json.loads(reply.split(b"\r\n\r\n")[-1]) == {
            "ok": False, "error": {"code": "bad_request", "message": "malformed HTTP request"}}
        # A half-open request (its body never completes) times out; the next call is then served.
        with socket.create_connection(("127.0.0.1", port), timeout=10) as stalled:
            stalled.sendall(b"POST /op HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{")
            started = time.monotonic()
            status = session.ok("status")
            waited = time.monotonic() - started
        assert 0.5 < waited < 20
        assert status["ops_used"] == 1          # other methods, paths and malformed HTTP are not operations
        records = custody(broker)
        assert [(r["op"], r["error_code"]) for r in records] == [
            ("register_inputs", None), (None, "not_found"), (None, "not_found"), (None, "not_found"),
            (None, "unauthorized"), (None, "bad_request"), (None, "request_timeout"), ("status", None)]
        assert [r["result"] for r in records[1:5]] == [{"method": m, "path": p} for m, p in (
            ("GET", "/op"), ("POST", "/other"), ("BREW", "/op"), ("DELETE", "/op"))]
        assert records[4]["incident"]["kind"] == "unauthorized_request"
        assert records[5]["result"]["http_status"] == 400
        # stop() returns although a client holds a half-open connection.
        with socket.create_connection(("127.0.0.1", port), timeout=10) as stalled:
            stalled.sendall(b"POST /op HTTP/1.1\r\n")
            started = time.monotonic()
            broker.stop()
            assert time.monotonic() - started < 15
    finally:
        broker.stop()


def test_stop_is_bounded_while_a_call_is_in_progress(tmp_path, monkeypatch):
    broker = new_broker(tmp_path / "broker", V2, prior=None)
    session = Session(broker)
    current, _ = session.handles()
    state = broker.root / "ravel-runs" / sha256_bytes(V2["workspace"])[:16] / "execution_state.json"
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fit = pool.submit(session.call, "fit", workspace=current["workspace"])
        deadline = time.monotonic() + 300
        while not fit.done() and time.monotonic() < deadline:
            if state.is_file() and '"running"' in state.read_text():
                break
            time.sleep(0.02)
        assert not fit.done(), "the fit stage finished before stop() could be exercised"
        monkeypatch.setattr(broker_module, "STOP_SECONDS", 0.2)
        with pytest.raises(RuntimeError, match="a call is still in progress"):
            broker.stop()
        assert fit.result(timeout=900)["ok"] is True         # the call in progress is answered and recorded
    broker.stop()
    last = custody(broker)[-1]
    assert (last["op"], last["ok"], last["stage"]["status"]) == ("fit", True, "executed")


def test_fit_applies_the_numerical_interface_checks(tmp_path):
    capped = {**V2, "workspace": encode(counting_workspace(42.0, 38.0, 5.0, poi_cap=10.0))}
    broker = new_broker(tmp_path / "broker", capped, prior=None)
    session = Session(broker)
    try:
        current, _ = session.handles()
        response = session.call("fit", workspace=current["workspace"])
        assert response["error"]["code"] == "stage_failed"
        assert "POI bounds must start at zero and contain poi_cap" in response["error"]["message"]
        entry = custody(broker)[-1]
        assert entry["stage"]["status"] == "failed" and entry["result"]["detail"]["exit_code"] != 0
    finally:
        broker.stop()
    # A prior that cannot be produced is terminal for its broker: no retry, no service.
    failed = Broker(tmp_path / "prior", guard_mode="audit", feedback="silent", budgets=BUDGETS,
                    python=sys.executable, env=STAGE_ENV, secret=SECRET)
    failed.register_inputs(V2)
    with pytest.raises(RuntimeError, match="prior fit stage failed"):
        failed.create_prior({**PRIOR, "workspace": capped["workspace"]})
    with pytest.raises(ContractError):
        failed.create_prior(PRIOR)
    with pytest.raises(ContractError):
        failed.start()
    last = custody(failed)[-1]
    assert (last["op"], last["error_code"], last["stage"]["status"]) == ("create_prior", "stage_failed", "failed")


def test_stage_workers_refuse_to_run_outside_the_supervisor(tmp_path):
    for name in stages.ORDER:
        done = subprocess.run([sys.executable, str(stages.worker_path(name)), str(tmp_path)],
                              env={**STAGE_ENV, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True)
        assert done.returncode != 0 and "RAVEL stage supervisor" in done.stderr
    assert list(tmp_path.iterdir()) == []


def test_broker_configuration_fails_closed(tmp_path):
    good = dict(guard_mode="block", feedback="diagnostic", budgets=BUDGETS, python=sys.executable,
                env=STAGE_ENV, secret=SECRET)
    for bad in ({"guard_mode": "block", "feedback": "silent"}, {"guard_mode": "off"},
                {"budgets": {"max_broker_ops": 0, "max_fits": 1}}, {"budgets": {"max_broker_ops": 1}},
                {"python": "python3"}, {"env": {**STAGE_ENV, "RAVEL_TASK_TOKEN": "synthetic-secret-value"}},
                {"env": {**STAGE_ENV, "AWS_SECRET_ACCESS_KEY": "synthetic-secret-value"}},
                {"env": {**STAGE_ENV, "HOME": "/synthetic-home"}},
                {"env": {k: v for k, v in STAGE_ENV.items() if k != "PYTHONPATH"}}, {"secret": b"short"}):
        with pytest.raises(ContractError) as caught:
            Broker(tmp_path / "unused", **{**good, **bad})
        assert "synthetic-secret-value" not in str(caught.value)
    assert not (tmp_path / "unused").exists()
    # The stages must import ravel from the pinned PYTHONPATH, not from an ambient install.
    with pytest.raises(ContractError, match="outside the pinned PYTHONPATH|cannot import ravel"):
        Broker(tmp_path / "unpinned", **{**good, "env": {**STAGE_ENV, "PYTHONPATH": str(tmp_path / "empty")}})
    (tmp_path / "used").mkdir()
    (tmp_path / "used" / "custody.jsonl").write_text("")
    with pytest.raises(ContractError):
        Broker(tmp_path / "used", **good)
    broker = Broker(tmp_path / "fresh", **good)
    assert broker._kernel_package == REPO / "src" / "ravel"
    with pytest.raises(ContractError):
        broker.start()
    with pytest.raises(ContractError):
        broker.register_inputs({"workspace": b"[]", "title": b"t"})
    broker.register_inputs({"workspace": PRIOR["workspace"], "title": PRIOR["title"]})
    with pytest.raises(ContractError):
        broker.register_inputs({"workspace": PRIOR["workspace"], "title": PRIOR["title"]})


def test_tool_guide_is_neutral():
    text = TOOLS.read_text()
    forbidden = re.compile(r"\b(arms?|treatments?|guards?|block\w*|enforc\w*|audit\w*|stale|oracle|"
                           r"feedback|diagnostics|incidents?|variants?)\b", re.IGNORECASE)
    assert forbidden.findall(text) == []
    for op in ("inputs", "show", "fit", "convert", "report", "submit", "note", "status"):
        assert f"ravel-task {op}" in text


def test_outside_state_sees_outside_writes_and_ignores_concurrent_local_runs(tmp_path):
    """Non-vacuous: in a SYNTHETIC repository with a linked worktree under its local-runs/ (as this checkout's
    worktrees are), planted writes to a tracked file, an untracked non-ignored file, an ignored file and a new
    entry in the worktree's or the main checkout's trial-runs/ change outside_state; writes under local-runs/
    (concurrent sessions) do not."""
    main = tmp_path / "main"
    (main / "trial-runs" / "run-a" / "output").mkdir(parents=True)
    (main / ".gitignore").write_text("/local-runs/\ntrial-runs/**/output/**\n")
    (main / "tracked.txt").write_text("SYNTHETIC tracked\n")
    (main / "trial-runs" / "run-a" / "notes.txt").write_text("SYNTHETIC\n")
    quiet = ["-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=synthetic",
             "-c", "user.email=synthetic@invalid"]
    for args in (["init", "-q"], ["add", "-A"], [*quiet, "commit", "-q", "-m", "SYNTHETIC"]):
        assert _git(main, *args).returncode == 0
    worktree = main / "local-runs" / "worktrees" / "probe"
    assert _git(main, *quiet, "worktree", "add", "--detach", str(worktree)).returncode == 0
    assert main_checkout(worktree) == main.resolve() and main_checkout(main) == main.resolve()
    (worktree / "trial-runs" / "run-a" / "output").mkdir(parents=True, exist_ok=True)
    (main / "local-runs" / "other-session").mkdir()

    def changes(write):
        before = outside_state(worktree)
        assert before is not None
        write()
        return outside_state(worktree) != before

    concurrent = [lambda: (worktree / "local-runs" / "store").mkdir(parents=True),
                  lambda: (worktree / "local-runs" / "store" / "run.json").write_text("{}"),
                  lambda: (main / "local-runs" / "other-session" / "journal.jsonl").write_text("{}")]
    for write in concurrent:
        assert not changes(write)
    planted = [lambda: (worktree / "tracked.txt").write_text("SYNTHETIC outside write\n"),
               lambda: (worktree / "stray.txt").write_text("SYNTHETIC"),
               lambda: (worktree / "trial-runs" / "run-a" / "output" / "limit.json").write_text("{}"),
               lambda: (worktree / "trial-runs" / "run-b").mkdir(),
               lambda: (main / "trial-runs" / "run-c").mkdir()]
    for i, write in enumerate(planted):
        assert changes(write), i


def test_nothing_is_written_outside_the_broker_roots(world, outside):
    started, before = outside
    session = world["v0"]
    session.ok("status")
    for other in world.values():
        root = other.broker.root
        assert {p.name for p in root.iterdir()} == {"artifacts", "blobs", "custody.jsonl", "ravel-runs",
                                                     "stage-home", "stage-tmp"}
        assert not any((root / "stage-home").iterdir()) and not any((root / "stage-tmp").iterdir())
    # Bytecode rewritten in place keeps git status unchanged: no kernel .pyc may be newer than this module.
    assert [p for p in (REPO / "src").rglob("*.pyc") if p.stat().st_mtime_ns > started] == []
    if before is None:
        pytest.skip("not a git checkout: repository status cannot be compared")
    assert outside_state() == before, "repository or trial-runs changed (see outside_state for concurrent writers)"
