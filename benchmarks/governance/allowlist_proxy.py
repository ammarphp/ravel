#!/usr/bin/env python3
"""Localhost HTTPS CONNECT proxy that tunnels only configured host:port pairs.

Runs in the coordinator, outside every sandbox. Seatbelt can filter network only by
`localhost` or `*` (Phase 0, host-and-sandbox §4.1 T2e), so a subject profile allows
outbound TCP only to localhost:<proxy port> and this proxy decides every onward connection.
Each request produces exactly one append-only JSON line (decision "allow", "deny" or "error",
the last also for any unexpected failure before a decision) in coordinator custody. Standard
library only.

    python3 benchmarks/governance/allowlist_proxy.py --log proxy.jsonl api.example.org:443
"""
from __future__ import annotations

import argparse
import re
import select
import signal
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from governance.canonical import ContractError, append_jsonl, require
else:
    from .canonical import ContractError, append_jsonl, require

MAX_HEADER_BYTES = 8192
HEADER_TIMEOUT_S = 10.0
IDLE_TIMEOUT_S = 300.0
HOSTNAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*")
IPV6 = re.compile(r"\[([0-9a-f:.]+)\]")
PORT = re.compile(r"[0-9]{1,5}")   # ASCII only: str.isdigit() accepts "²", which int() rejects


def parse_target(text: str):
    """(host, port) from "host:port" or "[v6]:port"; hosts lowercased; None if malformed."""
    host, sep, port = text.rpartition(":")
    if not sep or not PORT.fullmatch(port) or not 0 < int(port) < 65536:
        return None
    host = host.lower()
    match = IPV6.fullmatch(host)
    if match:
        return match.group(1), int(port)
    return (host, int(port)) if HOSTNAME.fullmatch(host) else None


def parse_allow(entries) -> frozenset:
    require(isinstance(entries, (list, tuple, set, frozenset)) and entries, "allow: expected a nonempty list")
    pairs = set()
    for entry in entries:
        target = parse_target(entry) if isinstance(entry, str) else None
        require(target is not None, f"allow: expected host:port, got {entry!r}")
        pairs.add(target)
    return frozenset(pairs)


class AllowlistProxy:
    """CONNECT-only proxy on 127.0.0.1. Anything that is not a well-formed CONNECT to an
    allowlisted (host, port) gets 400/403 and is never forwarded."""

    def __init__(self, allow, *, log_path, port=0, connect_timeout=10.0):
        self.allow = parse_allow(allow)
        self.log_path = Path(log_path)
        require(type(port) is int and 0 <= port < 65536, "port: expected a TCP port or 0")
        self.port, self.connect_timeout = port, connect_timeout
        self.decisions = []
        self._lock = threading.Lock()
        self._open = set()
        self._server = None
        self._thread = None
        self._stopping = threading.Event()

    def start(self) -> int:
        require(self._server is None, "proxy already started")
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", self.port))
        server.listen(64)
        server.settimeout(0.2)
        self._server, self.port = server, server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, name="allowlist-proxy", daemon=True)
        self._thread.start()
        return self.port

    def stop(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._server is not None:
            self._server.close()
        with self._lock:
            sockets = list(self._open)
        for sock in sockets:   # shutdown wakes a tunnel blocked in select()
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            _close(sock)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    def _serve(self):
        while not self._stopping.is_set():
            try:
                client, address = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self._track(client)
            threading.Thread(target=self._handle, args=(client, address), daemon=True).start()

    def _track(self, sock, remove=False):
        with self._lock:
            (self._open.discard if remove else self._open.add)(sock)

    def _record(self, address, request, target, decision, reason):
        record = {"time_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                  "client": f"{address[0]}:{address[1]}", "request": request,
                  "target": None if target is None else f"{target[0]}:{target[1]}",
                  "decision": decision, "reason": reason}
        with self._lock:
            record["seq"] = len(self.decisions) + 1
            append_jsonl(self.log_path, record)
            self.decisions.append(record)

    def _handle(self, client, address):
        upstream, request, decided = None, "", False

        def decide(target, decision, reason, reply=None):
            nonlocal decided
            self._record(address, request, target, decision, reason)
            decided = True
            if reply:
                client.sendall(reply)

        try:
            client.settimeout(HEADER_TIMEOUT_S)
            head, rest = _read_head(client)
            line = head.split(b"\r\n", 1)[0].decode("latin-1") if head is not None else ""
            request = "".join(c if 32 <= ord(c) < 127 else "?" for c in line)[:256]
            parts = line.split(" ")
            if head is None:
                return decide(None, "deny", "malformed_or_oversized_request", b"HTTP/1.1 400 Bad Request\r\n\r\n")
            if len(parts) != 3 or parts[0] != "CONNECT":
                return decide(None, "deny", "not_connect", b"HTTP/1.1 403 Forbidden\r\n\r\n")
            target = parse_target(parts[1])
            if target is None:
                return decide(None, "deny", "malformed_target", b"HTTP/1.1 400 Bad Request\r\n\r\n")
            if target not in self.allow:
                return decide(target, "deny", "not_allowlisted", b"HTTP/1.1 403 Forbidden\r\n\r\n")
            try:
                upstream = socket.create_connection(target, timeout=self.connect_timeout)
            except OSError as exc:
                return decide(target, "error", f"upstream_connect_failed: {exc.__class__.__name__}",
                              b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            self._track(upstream)
            decide(target, "allow", "allowlisted", b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
            _pipe(client, upstream)
        except Exception as exc:   # undecided: log an error; decided: tunnel teardown or stop()
            if not decided:
                try:
                    self._record(address, request, None, "error", f"internal_error: {exc.__class__.__name__}")
                except OSError:
                    pass
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    self._track(sock, remove=True)
                    _close(sock)


def _read_head(client):
    """(header bytes, bytes after the header) or (None, b"") on EOF, timeout or oversize."""
    data = b""
    while b"\r\n\r\n" not in data:
        if len(data) > MAX_HEADER_BYTES:
            return None, b""
        try:
            chunk = client.recv(4096)
        except OSError:
            return None, b""
        if not chunk:
            return None, b""
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return (head, rest) if len(head) <= MAX_HEADER_BYTES else (None, b"")


def _pipe(a, b):
    a.settimeout(None)
    b.settimeout(None)
    while True:
        ready, _, _ = select.select([a, b], [], [], IDLE_TIMEOUT_S)
        if not ready:
            return
        for sock in ready:
            data = sock.recv(65536)
            if not data:
                return
            (b if sock is a else a).sendall(data)


def _close(sock):
    try:
        sock.close()
    except OSError:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--log", required=True, help="append-only JSONL decision log")
    parser.add_argument("--port", type=int, default=0, help="127.0.0.1 port (0: ephemeral)")
    parser.add_argument("allow", nargs="+", help="allowed host:port")
    args = parser.parse_args(argv)
    try:
        proxy = AllowlistProxy(args.allow, log_path=args.log, port=args.port)
    except ContractError as exc:
        parser.error(str(exc))
    done = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: done.set())
    print(f"listening 127.0.0.1:{proxy.start()}", flush=True)
    done.wait()
    proxy.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
