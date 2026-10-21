"""P14 stretch: the governed-chat coordinator MCP only reads; it never approves, executes or submits."""
import json
import subprocess
import sys

import pytest

from ravel.controller.frontend import server

FORBIDDEN = ("approve", "answer", "respond", "launch", "execute", "run_stage", "submit", "stop", "write",
             "steer", "go", "ask", "drive")


@pytest.fixture
def root(tmp_path):
    rd = tmp_path / "runs" / "r1"
    (rd / "inputs").mkdir(parents=True)
    (rd / "run_state.json").write_text(json.dumps({"current_step": "plan", "next_required": {"what": "CHECK-IN 1"}}))
    (rd / "inputs/checkin1.json").write_text(json.dumps({"sections": {}}))
    (rd / "delivery").mkdir()
    (rd / "delivery/summary.md").write_text("result\n")
    (rd / "result.json").write_text(json.dumps({"enforcement": {"governance": {"label": "NOT GOVERNED"}}}))
    return tmp_path / "runs"


def test_tool_list_offers_reading_only():
    names = [tool["name"] for tool in server.TOOLS]
    assert names == ["run_status", "checkin_show", "deliveries_list", "explain"]
    for name in names:
        assert not any(verb in name.split("_") for verb in FORBIDDEN), name
    with pytest.raises(server.Refused):
        server.call([], "approve", {"run": "r1"})


def test_status_checkins_and_deliveries_are_read_with_the_label(root):
    status = server.run_status([root], "r1")
    assert status["current_step"] == "plan" and status["label"] == "NOT GOVERNED"
    shown = server.checkin_show([root], "r1")
    assert [d["path"] for d in shown["documents"]] == ["inputs/checkin1.json"]
    listed = server.deliveries_list([root], "r1")
    assert {row["path"] for row in listed["files"]} == {"delivery/summary.md", "result.json"}
    assert listed["recorded_label"] == "NOT GOVERNED"
    assert "check-ins" in server.explain("check-ins")["text"].lower()


@pytest.mark.parametrize("name", ["../r1", "/etc", "", "missing", "link"])
def test_paths_outside_the_roots_are_refused(root, tmp_path, name):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run_state.json").write_text("{}")
    (root / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(server.Refused):
        server.run_dir([root], name)


def test_malformed_tool_calls_are_refused_and_the_server_keeps_serving(root):
    for params in ({"name": "explain", "arguments": {"topic": ["start"]}},
                   {"name": ["run_status"], "arguments": {"run": "r1"}},
                   {"name": "run_status", "arguments": {"run": {"x": 1}}},
                   ["not", "an", "object"]):
        reply = server.handle([root], {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": params})
        assert reply["result"]["isError"] is True, params
    # Positive control: a well-formed call on the same server is answered.
    reply = server.handle([root], {"jsonrpc": "2.0", "id": 10, "method": "tools/call",
                                   "params": {"name": "explain", "arguments": {"topic": "start"}}})
    assert reply["result"]["isError"] is False


def test_symlinked_delivery_file_outside_the_run_is_not_listed(root, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("x")
    (root / "r1/delivery/leak.txt").symlink_to(secret)
    assert "delivery/leak.txt" not in {row["path"] for row in server.deliveries_list([root], "r1")["files"]}


def test_stdio_round_trip_never_writes(root):
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_status", "arguments": {"run": "r1"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "approve", "arguments": {"run": "r1"}}},
                {"jsonrpc": "2.0", "id": 5, "method": "checkin/answer"}]
    done = subprocess.run([sys.executable, "-m", "ravel.controller.frontend", "--root", str(root)],
                          input="".join(json.dumps(m) + "\n" for m in messages), text=True, capture_output=True)
    assert done.returncode == 0, done.stderr
    replies = {r["id"]: r for r in map(json.loads, done.stdout.splitlines())}
    assert set(replies) == {1, 2, 3, 4, 5}
    assert replies[1]["result"]["capabilities"] == {"tools": {}}
    assert json.loads(replies[3]["result"]["content"][0]["text"])["current_step"] == "plan"
    assert replies[4]["result"]["isError"] is True
    assert replies[5]["error"]["code"] == -32601
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before
