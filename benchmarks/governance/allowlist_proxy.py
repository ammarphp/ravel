#!/usr/bin/env python3
"""Localhost HTTPS CONNECT proxy that tunnels only configured host:port pairs.

Runs in the coordinator, outside every sandbox. Seatbelt can filter network only by
`localhost` or `*` (Phase 0, host-and-sandbox §4.1 T2e), so a subject profile allows
outbound TCP only to localhost:<proxy port> and this proxy decides every onward connection.
Each request produces exactly one append-only JSON line (decision "allow", "deny" or "error",
the last also for any unexpected failure before a decision) in coordinator custody.

Host attribution (smoke spec R6, WI-4). With ``owner_check`` a connection is served only when its
client socket belongs to the launch's host process: ``owner_check((client host, client port))``
answers True (the owner), False (another process: ``deny subject_client``) or None (the lookup
failed, or no owner is known yet: ``deny owner_unknown``, fail closed). The check runs as soon as a
connection is accepted, before anything is read from it, and its answer is recorded
(``attribution``: "owner", "other" or "unknown"); a proxy without ``owner_check`` serves and logs
exactly as before. ``stop(join_timeout)`` joins the accept thread and every handler thread (bounded)
after closing their sockets, so the log is complete when it returns; a thread still running is
reported in ``stop_error``, and a decision reached after ``stop`` returned is never written (it is
counted in ``late_decisions``, a coordinator integrity error).

IPv6 twin (E-82). A Seatbelt ``(remote tcp "localhost:P")`` rule admits both 127.0.0.1:P and [::1]:P, while
the proxy listens on 127.0.0.1 only, so ``start`` also binds [::1]:P, IPv6-only and never listening
(``reserve_ipv6_twin``): while it is held no other socket can take that address, nothing serves a
subject's connect to it (macOS drops the SYN, so the connect times out), and a port whose ::1 twin
another process holds is never picked (the next ephemeral port is tried). The broker reserves its port the same way. Upstream names are resolved with a bound
(``RESOLVE_TIMEOUT_S``, and at once when the proxy is stopping), so a stalled lookup never outlives
``stop``. Standard library only.

    python3 benchmarks/governance/allowlist_proxy.py --log proxy.jsonl api.example.org:443
"""
from __future__ import annotations

import argparse
import errno
import re
import select
import signal
import socket
import sys
import threading
import time
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
RESOLVE_TIMEOUT_S = 10.0
TWIN_ATTEMPTS = 16          # ephemeral ports tried before giving up when each one's ::1 twin is taken


class PortTaken(OSError):
    """The ::1 twin of a loopback port is held by another socket."""


def reserve_ipv6_twin(port):
    """A TCP socket bound to [::1]:port, IPv6-only and never listening (nothing serves a connect to it), or None when
    this host has no IPv6 loopback (then nothing else can listen there either). PortTaken when another socket holds
    it."""
    try:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    except OSError as exc:
        if exc.errno in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT):
            return None
        raise
    try:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        sock.bind(("::1", port))
    except OSError as exc:
        sock.close()
        if exc.errno == errno.EADDRINUSE:
            raise PortTaken(errno.EADDRINUSE, f"[::1]:{port} is held by another socket") from None
        if exc.errno == errno.EADDRNOTAVAIL:
            return None
        raise
    return sock


def _resolve(host, port, timeout, stopping):
    """getaddrinfo on a helper thread, bounded by ``timeout`` and abandoned at once when ``stopping`` is set (the
    blocked lookup is left to finish on its own daemon thread; nothing waits for it)."""
    box = {}

    def work():
        try:
            box["found"] = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except Exception as exc:   # handed to the caller
            box["error"] = exc
    thread = threading.Thread(target=work, name="allowlist-proxy-resolve", daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive():
        if stopping.is_set():
            raise OSError(errno.ECANCELED, "the proxy is stopping")
        if time.monotonic() >= deadline:
            raise socket.timeout(f"resolving {host} took longer than {timeout:g} s")
        thread.join(0.05)
    if "error" in box:
        raise box["error"]
    return box["found"]


def _connect(target, timeout, stopping):
    """socket.create_connection with a bounded, stop-aware name resolution."""
    last = None
    for family, kind, proto, _, address in _resolve(target[0], target[1], timeout, stopping):
        sock = socket.socket(family, kind, proto)
        try:
            sock.settimeout(timeout)
            sock.connect(address)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError(errno.EHOSTUNREACH, f"no address for {target[0]}")


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
    allowlisted (host, port) gets 400/403 and is never forwarded. With ``owner_check`` a client
    that is not the owner (``owner_pid``, set by the coordinator once the host started) is denied
    whatever it asks for (module docstring)."""

    def __init__(self, allow, *, log_path, port=0, connect_timeout=10.0, owner_check=None):
        self.allow = parse_allow(allow)
        self.log_path = Path(log_path)
        require(type(port) is int and 0 <= port < 65536, "port: expected a TCP port or 0")
        require(owner_check is None or callable(owner_check), "owner_check: a callable or None")
        self.port, self.connect_timeout = port, connect_timeout
        self.owner_check = owner_check
        self.owner_pid = None        # the launch's host process, set by the recorder's on_start
        self.decisions = []
        self.stop_error = None
        self.late_decisions = 0
        self._lock = threading.Lock()
        self._open = set()
        self._handlers = set()
        self._server = None
        self._twin = None
        self._thread = None
        self._stopped = False
        self._stopping = threading.Event()

    def start(self) -> int:
        """Listen on 127.0.0.1 (``port``, or an ephemeral one) and hold its [::1] twin (module docstring)."""
        require(self._server is None, "proxy already started")
        for _ in range(TWIN_ATTEMPTS if self.port == 0 else 1):
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server.bind(("127.0.0.1", self.port))
                twin = reserve_ipv6_twin(server.getsockname()[1])
            except PortTaken:
                server.close()
                continue
            except BaseException:
                server.close()
                raise
            break
        else:
            raise OSError(errno.EADDRINUSE, f"no 127.0.0.1 port whose [::1] twin is free after {TWIN_ATTEMPTS} tries")
        server.listen(64)
        server.settimeout(0.2)
        self._server, self._twin, self.port = server, twin, server.getsockname()[1]
        self._thread = threading.Thread(target=self._serve, name="allowlist-proxy", daemon=True)
        self._thread.start()
        return self.port

    def stop(self, join_timeout=10.0) -> None:
        """Stop accepting, shut down every open socket (that wakes a tunnel blocked in select() or a
        handler waiting for its request) and join the accept and handler threads within
        ``join_timeout`` seconds in all; each handler closes its own sockets, and any socket still open
        after the joins is closed here. A socket is never closed while its handler may still read it:
        on macOS a close() right after the shutdown() can leave a read that is already waiting blocked
        until its own timeout (the 10 s request-line timeout), so stop() would stall and could report
        a live handler. Threads still running are reported in ``stop_error``; no decision is written
        after this returns (``late_decisions``). Never signals anything."""
        deadline = time.monotonic() + join_timeout
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if self._server is not None:
            self._server.close()
        if self._twin is not None:
            _close(self._twin)
        with self._lock:
            sockets, handlers = list(self._open), list(self._handlers)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for thread in handlers:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._lock:
            leftover = list(self._open)
        for sock in leftover:   # only a handler that did not finish leaves its sockets open
            _close(sock)
        alive = [t for t in handlers if t.is_alive()]
        if self._thread is not None and self._thread.is_alive():
            alive.append(self._thread)
        with self._lock:
            self._stopped = True
            self.stop_error = (f"{len(alive)} proxy thread(s) still running {join_timeout:g} s after stop"
                               if alive else None)

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
            handler = threading.Thread(target=self._handle, args=(client, address), name="allowlist-proxy-handler",
                                       daemon=True)
            with self._lock:
                self._handlers.add(handler)
            handler.start()

    def _track(self, sock, remove=False):
        with self._lock:
            (self._open.discard if remove else self._open.add)(sock)

    def _record(self, address, request, target, decision, reason, attribution=None):
        record = {"time_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                  "client": f"{address[0]}:{address[1]}", "request": request,
                  "target": None if target is None else f"{target[0]}:{target[1]}",
                  "decision": decision, "reason": reason}
        if self.owner_check is not None:
            record["attribution"] = attribution
        with self._lock:
            if self._stopped:   # after stop() returned the log is closed: never written, counted
                self.late_decisions += 1
                return
            record["seq"] = len(self.decisions) + 1
            append_jsonl(self.log_path, record)
            self.decisions.append(record)

    def _attribute(self, address):
        """'owner', 'other' or 'unknown' (owner_check answered True, False, or None or raised)."""
        try:
            owned = self.owner_check(address)
        except Exception:   # a failed lookup fails closed
            owned = None
        return {True: "owner", False: "other"}.get(owned, "unknown")

    def _handle(self, client, address):
        upstream, request, decided = None, "", False
        attribution = None if self.owner_check is None else self._attribute(address)

        def decide(target, decision, reason, reply=None):
            nonlocal decided
            self._record(address, request, target, decision, reason, attribution)
            decided = True
            if reply:
                client.sendall(reply)

        try:
            client.settimeout(HEADER_TIMEOUT_S)
            head, rest = _read_head(client)
            line = head.split(b"\r\n", 1)[0].decode("latin-1") if head is not None else ""
            request = "".join(c if 32 <= ord(c) < 127 else "?" for c in line)[:256]
            parts = line.split(" ")
            if attribution is not None and attribution != "owner":
                target = parse_target(parts[1]) if head is not None and len(parts) == 3 else None
                return decide(target, "deny", "subject_client" if attribution == "other" else "owner_unknown",
                              b"HTTP/1.1 403 Forbidden\r\n\r\n")
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
                upstream = _connect(target, self.connect_timeout, self._stopping)
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
                    self._record(address, request, None, "error", f"internal_error: {exc.__class__.__name__}",
                                 attribution)
                except OSError:
                    pass
        finally:
            for sock in (client, upstream):
                if sock is not None:
                    self._track(sock, remove=True)
                    _close(sock)
            with self._lock:
                self._handlers.discard(threading.current_thread())


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
