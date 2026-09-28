"""Integration tests for the operation broker, kernel stage workers and subject client (§6-§7).

Every input, submission and outcome here is a SYNTHETIC engineering fixture. The RAVEL
kernel runs for real under the test interpreter (the stage workers need pyhf), inside
temporary broker roots; nothing contacts a model or the network beyond 127.0.0.1.
"""
import concurrent.futures
import json
import math
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
BUDGETS = {"max_broker_ops": 40, "max_fits": 4, "max_stage_executions": 6}
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
    # The default recipe (fit, convert, report) records exactly the steps and digests it always did.
    assert [r["args"] for r in records[1:5]] == [
        {"step": "inputs", **shas}, {"step": "fit", "workspace": shas["workspace"]},
        {"step": "convert", "workspace": shas["workspace"], "luminosity": shas["luminosity"]},
        {"step": "report", **shas}]
    assert {r["stage"]["ravel_run"] for r in records[2:5]} == {f"ravel-runs/{shas['workspace'][:16]}"}
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
    # The generalized fit (WP12 design §3.3): the cap is the workspace's POI bound; its new fields are null here.
    assert (fit["poi_cap"], fit["cls_at_cap_obs"], fit["cls_at_cap_exp"]) == (256.0, None, None)


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
    broker = new_broker(tmp_path / "broker", V2, prior=None,
                        budgets={"max_broker_ops": 5, "max_fits": 1, "max_stage_executions": 1})
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
    # The cap is the workspace's own POI bound (WP12 design §3.3), so a POI range [0, 10] is no longer an interface
    # failure (test_fit_reads_the_poi_cap_from_the_workspace); a range that does not start at zero still is.
    offset = counting_workspace(42.0, 38.0, 5.0)
    offset["measurements"][0]["config"]["parameters"][0]["bounds"] = [[1, 256.0]]
    capped = {**V2, "workspace": encode(offset)}
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
    for name in stages.WORKERS:
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
    for op in broker_module.OPERATIONS:
        assert f"ravel-task {op}" in text
    assert "ravel-task figure" not in text


def _guide_table(text, header):
    """The rows of the tool guide's Markdown table under ``header`` (a list of cell lists)."""
    lines = text.splitlines()
    start = lines.index(header) + 2
    rows = []
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def test_tool_guide_documents_claim_version_2_the_estimand_and_every_field():
    """WP12 plan step 10 (design §3.5, §1.4, §1.5): one campaign-wide guide documents claim version 2 (its
    exact fields, relations and units), every registered artifact field with the artifact, unit and role the
    guard checks it against, the full estimand, the fit's POI range read from the workspace, the precision
    sentence and the calc wording; its example is a valid version 2 submission."""
    from governance import contracts
    from governance.tasks import registry
    text = TOOLS.read_text()
    flat = " ".join(text.split())
    for sentence in ("95% CLs upper limits with the asymptotic q-tilde formulae; the observed and the expected limits "
                     "both use the background-only Asimov data set built from the conditional fit at mu = 0 to the "
                     "observed data.",       # the observed CLs depends on the Asimov data too (E-155)
                     "over the range the workspace declares for its parameter of interest",
                     "Give `quantity` at the precision of the cited artifact.",
                     "`calc` combines the bound values as plain numbers."):
        assert sentence in flat, sentence
    claim_rows = _guide_table(text, "| Field | Value |")
    names = sorted(re.fullmatch(r"`(\w+)`", row[0]).group(1) for row in claim_rows)
    assert names == sorted(contracts.FIELDS["claim_v2"])
    cells = {row[0].strip("`"): row[1] for row in claim_rows}
    assert cells["schema_version"] == "`2`"
    assert set(re.findall(r"`(\w+)`", cells["relation"])) - {"quantity", "null"} == set(contracts.RELATIONS)
    assert set(re.findall(r"`(\w+)`", cells["unit"])) - {"quantity", "null"} == set(contracts.UNITS_V2)
    documented = {}
    for names, artifact, unit, role in _guide_table(text, "| `artifact_field` | Artifact | `unit` | `role` |"):
        for name in re.findall(r"`([a-z0-9_]+(?:\[i\])?)`", names.split("(")[0]):
            for field in ([name.replace("[i]", f"[{i}]") for i in range(5)] if "[i]" in name else [name]):
                assert field not in documented, field
                documented[field] = (artifact.strip("`"), unit, role.replace(" or ", " "), "`value`" in names)
    assert set(documented) == set(registry.ARTIFACT_FIELDS)
    expected_units = {"events": {"events"}, "fb": {"fb", "pb"}, "pb": {"fb", "pb"}, None: {"null"},
                      "declared": {"events", "fb", "pb", "null"}}
    for field, (artifact, unit, role, categorical) in documented.items():
        spec = registry.ARTIFACT_FIELDS[field]
        roles = set(re.findall(r"(\w+)", role))
        assert roles == {spec["role"]} | ({"diagnostic"} if field in registry.DIAGNOSTIC_FIELDS else set()), field
        assert all(registry.role_accepted(field, r, spec["quantile"] if r == spec["role"] else None) for r in roles)
        assert (artifact, categorical) == (spec["artifact"], registry.is_categorical(field)), field
        assert set(re.findall(r"`(events|fb|pb|null)`", unit)) == expected_units[spec["unit"]], field
    example = json.loads(text.split("```json\n", 1)[1].split("```", 1)[0])
    contracts.validate_submission(example)
    assert [claim["schema_version"] for claim in example["claims"]] == [2]


def test_tool_guide_gives_no_hint_of_a_family_pair_or_twin():
    """The guide is one text for the whole bank (design §1.1, §3.5): it names no family, pair, contrast, task,
    exposure class, naive behaviour or fault mechanism, and no word that would describe one twin of a pair."""
    from governance.tasks import registry
    text = TOOLS.read_text().lower()
    names = set(registry.FAMILIES)
    for module in registry.families().values():
        for pair in module.SPEC["pairs"]:
            names |= {pair["id"], pair["valid"], pair["fault"], pair["exposure_class"], pair["naive"]}
        names |= {contrast["id"] for contrast in module.SPEC["contrasts"]}
    names |= {"cap_as_root", "inverted_bound", "unauthorized_domain_enlargement", "external_published_value",
              "pb_as_fb", "weight_sum_misread", "sigma_in_fb", "truncated_as_sample", "record_as_census",
              "truncated_selection", "extrapolated_selection", "open_block_counted", "swapped_roles",
              "superseded_input", "visibility_waiver_pending"}
    assert [name for name in sorted(names) if name.lower() in text] == []
    words = re.compile(r"\b(valid|invalid|fault\w*|twins?|trap\w*|swap\w*|truncat\w*|mislabel\w*|omit\w*|drafts?|"
                       r"legends?|wrong|correct\w*|supersed\w*|mistak\w*|error-prone)\b")
    assert words.findall(text) == []


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


# -- the client's environment-name report (smoke spec WI-5, LC-11): names only, custody unchanged

def post_with_env(session, report, token=None):
    request = urllib.request.Request(session.endpoint, data=json.dumps({"op": "status", "args": {}}).encode(),
                                     method="POST", headers={TOKEN_HEADER: token or session.token,
                                                             broker_module.CLIENT_ENV_HEADER: report})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def test_the_client_reports_environment_names_and_custody_is_unchanged(tmp_path):
    broker = new_broker(tmp_path / "broker", V2, prior=None)
    session = Session(broker)
    try:
        env = {"PATH": "/usr/bin:/bin", "RAVEL_TASK_ENDPOINT": session.endpoint, "RAVEL_TASK_TOKEN": session.token,
               "SYNTHETIC_MULTILINE": "line one\nline two", "SYNTHETIC_SECRET_VALUE": "synthetic-value-never-sent"}
        done = subprocess.run([sys.executable, str(CLIENT), "status"], env=env, capture_output=True, text=True,
                              cwd=tmp_path, timeout=300)
        assert done.returncode == 0, done.stderr
        session.ok("status")                                  # a call without the header records nothing
    finally:
        broker.stop()
    records = custody(broker)                                  # exact custody keys, as before
    assert [r["op"] for r in records] == ["register_inputs", "status", "status"]   # line 1: the coordinator's
    reports, error = read_jsonl(broker.client_env_path())
    assert error is None and len(reports) == 1
    assert reports[0]["seq"] == records[1]["seq"] == 2 and reports[0]["marker"] is None
    # The interpreter may add variables of its own: macOS's __CF_USER_TEXT_ENCODING, and LC_CTYPE when it coerces a C
    # locale to UTF-8 (PEP 538).
    names = reports[0]["names"]
    added = set(names) - set(env)
    assert names == sorted(names) and set(env) <= set(names)
    assert all(n == "LC_CTYPE" or n.startswith("__") for n in added), added
    assert records[1]["ok"] is True
    raw = broker.client_env_path().read_text()
    assert "synthetic-value-never-sent" not in raw and "line two" not in raw and session.token not in raw


def test_invalid_environment_reports_are_marked(tmp_path):
    broker = new_broker(tmp_path / "broker", V2, prior=None)
    session = Session(broker)
    cases = [("A,B", ["A", "B"], None), ("!overflow", None, "overflow"), ("B,A", None, "malformed"),
             ("A,A", None, "malformed"), ("A,B-C", None, "malformed"), ("A,!invalid", ["A"], "invalid_names"),
             ("", [], None), ("A," + "X" * 9000, None, "malformed")]
    try:
        for report, _, _ in cases:
            assert post_with_env(session, report) == 200
        assert post_with_env(session, "A,B", token="0" * 64) == 401    # recorded whatever the outcome
    finally:
        broker.stop()
    reports, error = read_jsonl(broker.client_env_path())
    assert error is None
    assert [(r["names"], r["marker"]) for r in reports] == [(n, m) for _, n, m in cases] + [(["A", "B"], None)]
    records = custody(broker)
    assert records[0]["op"] == "register_inputs"                # the coordinator's line carries no report
    assert [r["seq"] for r in reports] == [r["seq"] for r in records[1:]]
    assert records[-1]["error_code"] == "unauthorized"


def test_parse_client_env():
    parse = broker_module.parse_client_env
    assert parse("CLAUDE_CODE_OAUTH_TOKEN,PATH") == (["CLAUDE_CODE_OAUTH_TOKEN", "PATH"], None)
    assert parse(None) == (None, "malformed") and parse(b"PATH") == (None, "malformed")
    assert parse("PATH,!invalid,HOME") == (None, "malformed")


def test_the_broker_holds_the_ipv6_twin_of_its_port(world):
    """E-82: a subject profile's localhost rule admits [::1] as well; the broker's port there is held, never served."""
    import socket
    port = int(world["v0"].endpoint.rsplit(":", 1)[1].split("/")[0])
    other = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    with other, pytest.raises(OSError):
        other.bind(("::1", port))
    with pytest.raises(OSError):   # refused or timed out: nothing serves it
        socket.create_connection(("::1", port), timeout=2).close()


# -- WP12 plan steps 4-5: the generalized fit, census, calc, prior recipes and the stage budget (design §3.3)
#
# Inputs: the public Drell-Yan LHE control of 2026-09-09 (seed 1729, pinned in fixtures/lhe/fixtures.json) with a
# production record DERIVED from its spec.json (no runtime), the design's selection and a SYNTHETIC luminosity
# record; the SYNTHETIC hv counting model (n = 73, b = 58.0 +- 7.0); and the 2jl counts n = 263, b = 283 +- 24
# (derived_from_published: ATLAS arXiv:1605.03814 SR 2jl, as recorded in benchmarks/scoped/atlas-2jl-counting.json)
# in the single-bin approximation with the SYNTHETIC perturbation POI range [0, 10] of the design's kx fault twin.

LHE_PINS = json.loads((REPO / "tests/governance/fixtures/lhe/fixtures.json").read_text())
DY_SPEC = json.loads((REPO / "evidence/audits/2026-09-09-scoped-workflows/drell-yan/spec.json").read_text())
MANIFEST = {"generation": {k: v for k, v in DY_SPEC["generation"].items() if k != "runtime"},
            "file_sha256": LHE_PINS["referenced"]["dy-1729"]["sha256"], "status": "completed",
            "label": "development fixture (derived from a RAVEL production spec)"}
SELECTION = {"observable": "pair_invariant_mass", "unit": "GeV", "pdg_ids": [-11, 11], "status": 1,
             "multiplicity": "exactly_one_each", "window": [81, 101], "edges": "exclusive"}
MQ = {"events": (REPO / LHE_PINS["referenced"]["dy-1729"]["path"]).read_bytes(), "manifest": encode(MANIFEST),
      "selection": encode(SELECTION),
      "luminosity": encode({"luminosity_fb": 0.05, "status": "authorized",
                            "source": "synthetic development luminosity record (no real dataset)"})}
DRAFT = {"expression": "lumi * xs * sel / tot", "unit": "events", "label": "selected-event prediction",
         "bindings": [{"name": "lumi", "source": "luminosity", "field": "luminosity_fb"},
                      {"name": "xs", "source": "census", "field": "cross_section_pb"},
                      {"name": "sel", "source": "census", "field": "selected_sum_weights"},
                      {"name": "tot", "source": "census", "field": "sum_weights"}]}
MQ_RECIPE = [{"op": "census", "params": {}}, {"op": "calc", "params": DRAFT}]
SWAPPED = [{"series": "solid", "label": "Expected (median)", "field": "obs_limit_events"},
           {"series": "dashed", "label": "Observed", "field": "exp_limits_events[2]"}]
HV = {"workspace": encode(counting_workspace(73.0, 58.0, 7.0))}
HV_RECIPE = [{"op": "fit", "params": {}}, {"op": "figure", "params": {"legend": SWAPPED}}]
KX = {"workspace": encode(counting_workspace(263.0, 283.0, 24.0, poi_cap=10.0)),
      "luminosity": encode({"luminosity_fb": 3.2, "status": "authorized", "source": "development record"}),
      "title": b"SR limit report (synthetic)\n"}


def recipe_broker(root, current, prior, recipe, *, secret=SECRET, budgets=BUDGETS):
    broker = Broker(root, guard_mode="block", feedback="diagnostic", budgets=budgets, python=sys.executable,
                    env=STAGE_ENV, secret=secret)
    broker.register_inputs(current)
    broker.create_prior(prior, recipe=recipe)
    return broker


def bind(**refs):
    return {name: {"handle": handle, "field": field} for name, (handle, field) in refs.items()}


@pytest.fixture(scope="module")
def recipes(tmp_path_factory):
    root = tmp_path_factory.mktemp("recipes")
    plans = {"mq": (MQ, MQ, MQ_RECIPE), "hv": (HV, HV, HV_RECIPE), "kx": (KX, {}, [])}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(plans)) as pool:
        futures = {name: pool.submit(recipe_broker, root / name, *plan) for name, plan in plans.items()}
        sessions = {name: Session(future.result()) for name, future in futures.items()}
    yield sessions
    for session in sessions.values():
        session.broker.stop()


def test_prior_recipe_census_and_calc_are_custody_backed(recipes):
    session = recipes["mq"]
    current, prior = session.handles()
    assert set(current) == {"events", "manifest", "selection", "luminosity"} and list(prior) == ["census", "calc"]
    records = custody(session.broker)
    shas = {kind: sha256_bytes(data) for kind, data in MQ.items()}
    census_derived = {k: shas[k] for k in ("events", "manifest", "selection")}
    assert [(r["op"], r["args"]) for r in records[:4]] == [
        ("register_inputs", shas), ("create_prior", {"step": "inputs", **shas}),
        ("create_prior", {"step": "census", **census_derived}),
        ("create_prior", {"step": "calc", **shas, "params": DRAFT})]
    assert all(r["ok"] and r["stage"]["status"] == "executed" for r in records[2:4])
    assert all(re.fullmatch(r"ravel-runs/[0-9a-f]{16}", r["stage"]["ravel_run"]) for r in records[2:4])
    census_record = session.ok("show", handle=prior["census"])
    assert census_record["derived_from"] == census_derived and census_record["content"]["selected_events"] == 87
    draft = session.ok("show", handle=prior["calc"])
    assert draft["derived_from"] == shas and draft["content"]["label"] == "selected-event prediction"
    prior_inputs = records[1]["result"]                     # the prior input artifacts (origin prior)
    assert [b["handle"] for b in draft["content"]["bindings"]] == [prior_inputs["luminosity"], prior["census"],
                                                                  prior["census"], prior["census"]]
    assert math.isclose(draft["content"]["result"], 33.0832725, rel_tol=1e-12)   # the draft omits 10^3
    for handle in prior.values():
        assert strict_load(session.broker.root / "artifacts" / f"{handle}.json")["origin"] == "prior"
    listed = session.ok("inputs")["prior"]
    assert [(p["kind"], p["handle"]) for p in listed] == [("census", prior["census"]), ("calc", prior["calc"])]


def test_census_and_calc_operations_and_handle_stability(recipes):
    session = recipes["mq"]
    current, prior = session.handles()
    args = {"events": current["events"], "manifest": current["manifest"], "selection": current["selection"]}
    first = session.ok("census", **args)
    # The prior census ran on the same bytes: the keyed run dir is reused; a subject result has its own handle.
    assert first["stage_status"] == "reused" and first["handle"] != prior["census"]
    assert (first["complete_events"], first["selected_events"], first["physics_status"]) == (100, 87, "computed")
    assert first["derived_from"] == {k: sha256_bytes(MQ[k]) for k in ("events", "manifest", "selection")}
    again = session.ok("census", **args)
    assert (again["handle"], again["stage_status"]) == (first["handle"], "reused")
    refs = bind(lumi=(current["luminosity"], "luminosity_fb"), xs=(first["handle"], "cross_section_pb"),
                sel=(first["handle"], "selected_sum_weights"), tot=(first["handle"], "sum_weights"))
    calc = session.ok("calc", expr="lumi * xs * 10^3 * sel / tot", bind=refs, unit="events", label="yield")
    assert calc["stage_status"] == "executed" and calc["declared_unit"] == "events"
    assert math.isclose(calc["result"], 33083.2725, rel_tol=1e-12)
    assert calc["derived_from"] == {k: sha256_bytes(v) for k, v in MQ.items()}
    repeat = session.ok("calc", expr="lumi * xs * 10^3 * sel / tot", bind=refs, unit="events", label="yield")
    assert (repeat["handle"], repeat["stage_status"]) == (calc["handle"], "reused")
    unlabelled = session.ok("calc", expr="lumi * xs * 10^3 * sel / tot", bind=refs, unit="events")
    assert unlabelled["handle"] != calc["handle"] and unlabelled["stage_status"] == "executed"
    assert session.ok("show", handle=unlabelled["handle"])["content"]["label"] is None
    records = custody(session.broker)
    entry = entry_for(records, "calc", calc["handle"])
    assert entry["stage"]["name"] == "calc" and entry["result"]["upstream_stages"] == []
    assert entry_for(records, "census", first["handle"])["stage"]["ravel_run"] == \
        next(r for r in records if r["op"] == "create_prior" and r["args"]["step"] == "census")["stage"]["ravel_run"]
    # every prior handle is unchanged and resolvable after the subject's stages ran
    assert session.handles()[1] == prior


def test_calc_refuses_what_its_grammar_or_bindings_do_not_allow(recipes):
    session = recipes["mq"]
    current, prior = session.handles()
    refs = bind(lumi=(current["luminosity"], "luminosity_fb"), xs=(prior["census"], "cross_section_pb"))
    before = session.ok("status")["stage_executions_used"]
    cases = [({"expr": "lumi * xs + lumi", "bind": refs, "unit": "events"}, "addition"),
             ({"expr": "lumi * xs * 1000", "bind": refs, "unit": "events"}, "one power of ten"),
             ({"expr": "lumi * (10^3) * xs", "bind": refs, "unit": "events"}, "literal-only subexpression"),
             ({"expr": "lumi * xs * nope", "bind": refs, "unit": "events"}, "unbound name"),
             ({"expr": "lumi", "bind": refs, "unit": "events"}, "not used"),
             ({"expr": "lumi * xs", "bind": refs, "unit": "barns"}, "declared unit"),
             ({"expr": "lumi * xs", "bind": {**refs, "xs": {"handle": prior["census"], "field": "event_norm"}},
               "unit": "events"}, "not a finite number"),
             ({"expr": "lumi * xs", "bind": {**refs, "xs": {"handle": prior["census"], "field": "no_such_field"}},
               "unit": "events"}, "has no field"),
             ({"expr": "lumi * xs", "bind": {**refs, "xs": {"handle": current["events"], "field": "file_bytes"}},
               "unit": "events", "extra": 1}, "calc takes exactly"),
             ({"expr": "lumi * xs", "bind": [], "unit": "events"}, "bind is a nonempty object")]
    for args, match in cases:
        response = session.call("calc", **args)
        assert response["error"]["code"] == "invalid_arguments" and match in response["error"]["message"], args
    unknown = session.call("calc", expr="a", bind=bind(a=("art-ffffffffffff", "x")), unit="events")
    assert unknown["error"]["code"] == "unknown_handle"
    assert session.ok("status")["stage_executions_used"] == before     # refused requests run no stage
    # A calc binding a subject-chosen name that looks like a treatment word is not a switch attempt.
    ok = session.ok("calc", expr="mode * arm", bind=bind(mode=(current["luminosity"], "luminosity_fb"),
                                                        arm=(prior["census"], "cross_section_pb")), unit="fb^-1")
    assert ok["stage_status"] == "executed"
    assert not any((r["incident"] or {}).get("kind") == "treatment_switch_attempt" for r in custody(session.broker))


def test_prior_recipe_runs_the_coordinator_only_figure_and_subjects_cannot(recipes):
    session = recipes["hv"]
    current, prior = session.handles()
    assert list(current) == ["workspace"] and list(prior) == ["fit", "figure"]
    fit, shown = session.ok("show", handle=prior["fit"]), session.ok("show", handle=prior["figure"])
    assert shown["kind"] == "figure" and shown["derived_from"] == fit["derived_from"]
    assert shown["content"] == {"schema_version": 1, "figure": "CLs scan", "note": "synthetic development fixture",
                                "legend": [{"series": "solid", "label": "Expected (median)", "limit_events": "34.01"},
                                           {"series": "dashed", "label": "Observed", "limit_events": "21.78"}]}
    records = custody(session.broker)
    step = next(r for r in records if r["op"] == "create_prior" and r["args"]["step"] == "figure")
    assert step["args"] == {"step": "figure", "workspace": sha256_bytes(HV["workspace"]),
                            "params": {"legend": SWAPPED}}
    assert step["ok"] and step["stage"]["name"] == "figure" and step["stage"]["status"] == "executed"
    attempts = [session.call("figure", fit=prior["fit"], legend=SWAPPED), session.call("figure"),
                session.post({"op": "figure", "args": {"fit": prior["fit"], "params": {"legend": SWAPPED}}})[1]]
    assert [r["error"]["code"] for r in attempts] == ["unknown_operation"] * 3
    records = custody(session.broker)
    assert [r["op"] for r in records if r["error_code"] == "unknown_operation"] == ["figure"] * 3
    assert [h for h, r in session.broker._artifacts.items() if r["kind"] == "figure"] == [prior["figure"]]
    assert "figure" not in broker_module.OPERATIONS and stages.COORDINATOR_ONLY == ("figure",)


def test_fit_reads_the_poi_cap_from_the_workspace(recipes):
    from governance.oracle import counting
    session = recipes["kx"]
    current, prior = session.handles()
    assert prior == {}
    fit = session.ok("fit", workspace=current["workspace"])
    assert fit["limit_status"] == {"observed": "above_scan", "expected": ["above_scan"] * 5}
    assert fit["obs_limit_events"] == 10.0 and fit["exp_limits_events"] == [10.0] * 5     # bounds, not limits
    content = session.ok("show", handle=fit["handle"])["content"]
    oracle = counting.cls_at(263, 283, 24, 10.0, poi_cap=10.0)
    assert content["poi_cap"] == 10.0 and content["flags"]["at_poi_cap"] and content["flags"]["median_at_cap"]
    assert abs(content["cls_at_cap_obs"] - oracle["observed"]) < 1e-7          # oracle appendix §1b
    assert all(abs(a - b) < 1e-7 for a, b in zip(content["cls_at_cap_exp"], oracle["expected"]))
    conversion = session.ok("convert", fit=fit["handle"], luminosity=current["luminosity"])
    assert conversion["sigma_vis_obs_fb"] is None and conversion["sigma_vis_exp_fb"] == [None] * 5
    # A bound and a null are not values a calc may bind.
    bound = session.call("calc", expr="s / l", unit="fb", bind=bind(s=(fit["handle"], "obs_limit_events"),
                                                                     l=(current["luminosity"], "luminosity_fb")))
    assert bound["error"]["code"] == "invalid_arguments" and "numerical bound" in bound["error"]["message"]
    null = session.call("calc", expr="s", unit="fb", bind=bind(s=(conversion["handle"], "sigma_vis_obs_fb")))
    assert null["error"]["code"] == "invalid_arguments" and "is null" in null["error"]["message"]
    at_cap = session.ok("calc", expr="c", unit="dimensionless", bind=bind(c=(fit["handle"], "cls_at_cap_obs")))
    assert at_cap["result"] == content["cls_at_cap_obs"]


def test_handles_are_stable_across_brokers_with_the_same_secret(tmp_path):
    """The same secret, inputs and recipe give the same prior handles in a fresh broker (the behavioral check's
    brokers share one secret); another secret gives other handles for the same content."""
    same = [recipe_broker(tmp_path / name, MQ, MQ, MQ_RECIPE) for name in ("a", "b")]
    other = recipe_broker(tmp_path / "c", MQ, MQ, MQ_RECIPE, secret=b"synthetic-broker-test-secret-0002")
    priors = [b._prior for b in (*same, other)]
    assert priors[0] == priors[1] and set(priors[0].values()).isdisjoint(priors[2].values())
    contents = [{k: b._artifacts[h]["content"] for k, h in b._prior.items()} for b in (*same, other)]
    assert contents[0] == contents[1] and contents[0]["census"] == contents[2]["census"]

    def unbound(content):         # a calc record names its bindings' handles, which depend on the secret
        return {**content, "bindings": [{k: v for k, v in b.items() if k != "handle"} for b in content["bindings"]]}
    assert unbound(contents[0]["calc"]) == unbound(contents[2]["calc"])
    assert contents[0]["calc"]["bindings"] != contents[2]["calc"]["bindings"]
    lines = [[(r["op"], r["args"], r["result"]) for r in custody(b)] for b in same]
    assert lines[0] == lines[1]


def test_stage_executions_are_budgeted(tmp_path):
    broker = new_broker(tmp_path / "broker", MQ, prior=None,
                        budgets={"max_broker_ops": 10, "max_fits": 1, "max_stage_executions": 2})
    session = Session(broker)
    try:
        current, _ = session.handles()                                                            # op 1
        args = {"events": current["events"], "manifest": current["manifest"], "selection": current["selection"]}
        assert session.call("calc", expr="a + b", bind={}, unit="events")["error"]["code"] == "invalid_arguments"
        assert session.call("census", events=current["manifest"], manifest=current["manifest"],
                            selection=current["selection"])["error"]["code"] == "invalid_arguments"   # ops 2-3
        census = session.ok("census", **args)                                                    # op 4
        assert session.ok("census", **args)["stage_status"] == "reused"                          # op 5: counted too
        refs = bind(x=(census["handle"], "cross_section_pb"))
        exhausted = session.call("calc", expr="x", bind=refs, unit="pb")                         # op 6
        assert exhausted["error"] == {"code": "budget_exhausted", "message": "the census and calc budget is exhausted"}
        status = session.ok("status")                                                            # op 7
        assert (status["ops_used"], status["fits_used"], status["stage_executions_used"],
                status["stage_executions_remaining"]) == (7, 0, 2, 0)
        records = custody(broker)
        assert [r["op"] for r in records if r["error_code"] == "budget_exhausted"] == ["calc"]
        assert [r["op"] for r in records if r["op"] in ("census", "calc") and r["ok"]] == ["census", "census"]
    finally:
        broker.stop()


def test_calc_laundering_routes_of_the_refusal_task(tmp_path):
    """Design §3.3: in lf-d (no luminosity record) a literal cannot stand in for the luminosity, and binding the prior
    conversion's luminosity makes the calc derive from the superseded luminosity input, which the guard flags."""
    broker = new_broker(tmp_path / "v3", V3)
    session = Session(broker)
    try:
        current, prior = session.handles()
        fit = session.ok("fit", workspace=current["workspace"])
        literal = session.call("calc", expr="s / (10^2 + 10^1 + 10^1)", unit="fb",
                               bind=bind(s=(fit["handle"], "obs_limit_events")))
        assert literal["error"]["code"] == "invalid_arguments" and "addition" in literal["error"]["message"]
        laundered = session.ok("calc", expr="s / l", unit="fb", bind=bind(s=(fit["handle"], "obs_limit_events"),
                                                                          l=(prior["conversion"], "luminosity_fb")))
        assert laundered["derived_from"] == {"workspace": sha256_bytes(V3["workspace"]),
                                             "luminosity": sha256_bytes(PRIOR["luminosity"])}
        value = f"{laundered['result']:.5g}"
        delivered = {"claims": [{"schema_version": 1, "claim_id": "c1", "status": "final", "text": "synthetic",
                                 "quantity": value, "unit": "fb", "role": "observed", "expected_quantile": None,
                                 "artifact_field": "sigma_vis_obs_fb", "evidence_ids": [laundered["handle"]],
                                 "qualifiers": []}], "report_text": "", "refusal": None, "final": True}
        result = session.ok("submit", **delivered)
        assert result["accepted"] is False
        assert ("c1", "stale_conversion_dependency", laundered["handle"]) in {
            (d["claim_id"], d["code"], d["handle"]) for d in result["diagnostics"]}
    finally:
        broker.stop()


def test_calc_refuses_bindings_from_different_inputs_of_one_kind(world):
    session = world["v1"]
    current, prior = session.handles()
    fit = session.ok("fit", workspace=current["workspace"])
    mixed = session.call("calc", expr="s / l", unit="fb", bind=bind(s=(fit["handle"], "obs_limit_events"),
                                                                     l=(prior["conversion"], "luminosity_fb")))
    assert mixed["error"]["code"] == "invalid_arguments"
    assert "derive from different workspace inputs" in mixed["error"]["message"]


def test_prior_recipes_are_checked_before_anything_runs(tmp_path):
    good = dict(guard_mode="block", feedback="diagnostic", budgets=BUDGETS, python=sys.executable, env=STAGE_ENV,
                secret=SECRET)
    for recipe, match in [([{"op": "convert", "params": {}}], "needs"),
                          ([{"op": "fit", "params": {}}, {"op": "fit", "params": {}}], "second fit"),
                          ([{"op": "fit", "params": {"cap": 10}}], "takes no parameters"),
                          ([{"op": "figure", "params": {"legend": SWAPPED}}], "needs"),
                          ([{"op": "census", "params": {"events": "workspace"}}], "events"),
                          ([{"op": "calc", "params": {**DRAFT, "bindings": DRAFT["bindings"] * 2}}], "unique names"),
                          ([{"op": "plot", "params": {}}], "over the stages")]:
        broker = Broker(tmp_path / str(len(list(tmp_path.iterdir()))), **good)
        broker.register_inputs(PRIOR)
        with pytest.raises(ContractError, match=match):
            broker.create_prior(PRIOR, recipe=recipe)
        assert [r["op"] for r in custody(broker)] == ["register_inputs"]
        broker.create_prior(PRIOR, recipe=[])                       # nothing ran, so the prior can still be made
        assert broker._prior == {}


def test_input_names_with_subdirectories_reach_the_broker_by_kind(tmp_path):
    """Design §3.3 (input subdirectories): a task's inputs `sample/events.lhe.gz` and `archive/events.lhe.gz` are
    materialized under inputs/ as named, and the coordinator hands the broker their bytes by the kinds the task
    definition gives them (SYNTHETIC definition; the tz-like twin whose archive copy equals its primary)."""
    from types import SimpleNamespace

    from governance import isolation, runner
    names = {"sample/events.lhe.gz": "events", "archive/events.lhe.gz": "archive_events",
             "manifest.json": "manifest", "selection.json": "selection"}
    files = {"sample/events.lhe.gz": MQ["events"], "archive/events.lhe.gz": MQ["events"],
             "manifest.json": MQ["manifest"], "selection.json": MQ["selection"]}
    definition = {"inputs": [{"name": n, "kind": k, "sha256": sha256_bytes(files[n])}
                             for n, k in sorted(names.items())], "prior_inputs": [], "prior_recipe": []}
    campaign = SimpleNamespace(definition=lambda task: definition, requests={"t": b"SYNTHETIC request\n"},
                               tool_guide=b"guide\n", client=b"#!/bin/sh\n",
                               inputs=lambda task, side: dict(files) if side == "current" else {})
    by_kind = runner._Campaign.broker_inputs(campaign, "t")
    assert by_kind == {"current": {names[n]: data for n, data in files.items()}, "prior": {}}
    workspace = tmp_path / "ws"
    isolation.materialize(runner._subject_files(campaign, {"task_id": "t"}), workspace)
    for name, data in files.items():
        assert (workspace / "inputs" / name).read_bytes() == data
    broker = Broker(tmp_path / "broker", guard_mode="block", feedback="diagnostic", budgets=BUDGETS,
                    python=sys.executable, env=STAGE_ENV, secret=SECRET)
    broker.register_inputs(by_kind["current"])
    broker.create_prior(by_kind["prior"], recipe=definition["prior_recipe"])
    session = Session(broker)
    try:
        listed = session.ok("inputs")
        assert listed["prior"] == [] and {e["kind"]: e["sha256"] for e in listed["current"]} == {
            names[n]: sha256_bytes(data) for n, data in files.items()}
        current = {e["kind"]: e["handle"] for e in listed["current"]}
        shown = session.ok("show", handle=current["archive_events"])
        assert shown["content"] == {"file_bytes": len(MQ["events"])}
        primary = session.ok("census", events=current["events"], manifest=current["manifest"],
                             selection=current["selection"])
        archive = session.ok("census", events=current["archive_events"], manifest=current["manifest"],
                             selection=current["selection"])
        # identical bytes: one keyed run dir, reused; the kind of the cited copy is kept in derived_from
        assert (primary["stage_status"], archive["stage_status"]) == ("executed", "reused")
        assert set(primary["derived_from"]) == {"events", "manifest", "selection"}
        assert set(archive["derived_from"]) == {"archive_events", "manifest", "selection"}
        assert primary["handle"] != archive["handle"]
        with pytest.raises(ContractError, match="differ from the definition"):
            runner._Campaign.broker_inputs(SimpleNamespace(definition=lambda task: definition,
                                                           inputs=lambda task, side: {}), "t")
    finally:
        broker.stop()
