"""Context-bound, source-admitted and bounded controller acquisition HTTP.

Only requests actually admitted here appear in the audit. The scope remembers
failures so a discovery client's exception-to-status conversion cannot grant credit.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import http.client
import ipaddress
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import socket
import ssl
import tarfile
import time
import tempfile
import urllib.request
import urllib.parse
from dataclasses import dataclass
import zipfile

from . import private_files, restriction_guard

CHUNK = 1 << 20

_ACTIVE = ContextVar('ravel_controller_acquisition', default=None)


def current():
    return _ACTIVE.get()


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


class DestinationRefused(ValueError):
    """Sticky network admission refusal, distinct from HTTP absence/outage."""

    def __init__(self, reason, remedy):
        self.reason, self.remedy = reason, remedy
        super().__init__(f'controller acquisition destination refused: {reason}. Remedy: {remedy}')


@dataclass(frozen=True)
class Destination:
    host: str
    port: int
    family: int
    sockaddr: tuple


def _destination(url):
    remedy = 'supply a public HTTPS URL without userinfo'
    try:
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme.lower() != 'https' or not parts.hostname or
                parts.username is not None or parts.password is not None or
                any(ord(char) <= 32 or ord(char) == 127 for char in url) or
                '%' in parts.hostname or '\\' in parts.netloc):
            raise ValueError('HTTPS with an unambiguous host and no userinfo is required')
        host = parts.hostname
        port = parts.port if parts.port is not None else 443
        if port <= 0:
            raise ValueError('invalid destination port')
    except (ValueError, TypeError) as exc:
        raise DestinationRefused(str(exc), remedy) from exc
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM,
                                     proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise DestinationRefused('destination resolution failed',
                                 'repair public DNS and retry acquisition') from exc
    if not answers:
        raise DestinationRefused('destination resolution returned no addresses',
                                 'repair public DNS and retry acquisition')
    for family, socktype, proto, canonname, sockaddr in answers:
        try:
            address = ipaddress.ip_address(sockaddr[0])
            address = getattr(address, 'ipv4_mapped', None) or address
            allowed = (family in (socket.AF_INET, socket.AF_INET6) and address.is_global
                       and not address.is_multicast and not address.is_unspecified
                       and not address.is_reserved and not getattr(address, 'is_site_local', False))
        except (ValueError, IndexError):
            allowed = False
        if not allowed:
            raise DestinationRefused(
                'destination resolves to a non-global address',
                'use a public HTTPS endpoint; private services require a separately scoped '
                'trusted operator grant, whose acquisition transport is not yet qualified '
                '(descriptor flags cannot grant access)')
    family, _, _, _, sockaddr = answers[0]
    return Destination(host, port, family, sockaddr)


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to admitted numeric bytes; HTTPSConnection retains host for SNI/TLS."""

    def __init__(self, host, *, destination, **kwargs):
        super().__init__(host, **kwargs)
        self.destination = destination
        self._create_connection = self._connect_admitted

    def _connect_admitted(self, address, timeout, source_address=None):
        destination = self.destination
        origin = (address[0].casefold(), address[1])
        if (origin != (destination.host.casefold(), destination.port)
                or self._tunnel_host or source_address is not None):
            raise DestinationRefused('transport authority differs from admitted destination',
                                     'retry through the governed direct HTTPS transport')
        sock = socket.socket(destination.family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
        try:
            sock.settimeout(timeout)
            sock.connect(destination.sockaddr)
            return sock
        except BaseException:
            sock.close()
            raise


class PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        state = current()
        try:
            state.remaining()
            destination = getattr(req, '_ravel_destination', None)
            if destination is None or getattr(req, '_ravel_url', None) != req.full_url:
                destination = state.admit(req.full_url)
            context = self._context or ssl.create_default_context()
            if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
                raise DestinationRefused('TLS verification context is disabled',
                                         'use a verified TLS context with hostname checking')
            def connection(host, **kwargs):
                return PinnedHTTPSConnection(host, destination=destination, **kwargs)
            return self.do_open(connection, req, context=context)
        except Exception as exc:
            state.remember(exc)
            raise


class Acquisition:
    def __init__(self, run_dir, output, descriptor, max_bytes, wall_seconds):
        self.run_dir, self.output = run_dir, output
        self.descriptor = deepcopy(descriptor)
        self.max_bytes = max_bytes
        self.deadline = time.monotonic() + wall_seconds
        self.audit = {'requests': [], 'bytes': 0}
        self.failure = None

    def remember(self, exc):
        if self.failure is None:
            self.failure = exc

    def remaining(self):
        if self.failure is not None:
            raise self.failure
        left = self.deadline - time.monotonic()
        if left <= 0:
            exc = TimeoutError('controller acquisition deadline exceeded')
            self.remember(exc)
            raise exc
        return left

    def admit(self, url):
        try:
            self.remaining()
            descriptor = {**self.descriptor, 'url': url}
            restriction_guard.require('controller-acquisition', descriptor,
                                      rundir=self.run_dir, output=self.output)
            destination = _destination(url)
            self.remaining()
            self.audit['requests'].append({'url': url, 'descriptor_sha256': _digest(descriptor),
                                           'admission': 'restriction_guard.require',
                                           'destination_address': destination.sockaddr[0]})
            return destination
        except Exception as exc:
            self.remember(exc)
            raise


@contextmanager
def scope(run_dir, output, descriptor, max_bytes, wall_seconds):
    """Yield the request audit, failing even when a scoped client swallows errors."""
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('acquisition max_bytes must be a positive integer')
    if type(wall_seconds) not in (int, float) or not math.isfinite(wall_seconds) or wall_seconds <= 0:
        raise ValueError('acquisition wall_seconds must be positive and finite')
    if not isinstance(descriptor, dict):
        raise ValueError('acquisition descriptor must be an object')
    if current() is not None:
        raise ValueError('nested acquisition scopes are not admitted')
    state = Acquisition(run_dir, output, descriptor, max_bytes, wall_seconds)
    token = _ACTIVE.set(state)
    try:
        yield state.audit
        state.remaining()
    except Exception as exc:
        state.remember(exc)
        raise state.failure
    finally:
        _ACTIVE.reset(token)


class Response:
    """Delegate response metadata while all supported read paths consume one cap."""
    def __init__(self, response, state):
        self.response, self.state = response, state

    def __getattr__(self, name):
        return getattr(self.response, name)

    def __enter__(self):
        if hasattr(self.response, '__enter__'):
            self.response.__enter__()
        return self

    def __exit__(self, *args):
        if hasattr(self.response, '__exit__'):
            return self.response.__exit__(*args)
        self.response.close()

    def read(self, size=-1):
        if size == 0:
            return b''
        unlimited = size is None or size < 0
        chunks, received = [], 0
        reader = getattr(self.response, 'read1', None)
        if not callable(reader):
            reader = self.response.read
        while unlimited or received < size:
            remaining_time = self.state.remaining()
            fp = getattr(self.response, 'fp', None)
            raw = getattr(fp, 'raw', None) if fp is not None else None
            sock = getattr(raw, '_sock', None) if raw is not None else None
            if sock is not None:
                sock.settimeout(min(30, remaining_time))
            limit = self.state.max_bytes - self.state.audit['bytes'] + 1
            amount = min(65536, limit)
            if not unlimited:
                amount = min(amount, size - received)
            data = reader(amount)
            self.state.audit['bytes'] += len(data)
            if self.state.audit['bytes'] > self.state.max_bytes:
                exc = ValueError('controller acquisition response byte ceiling exceeded')
                self.state.remember(exc)
                raise exc
            self.state.remaining()
            if not data:
                break
            chunks.append(data)
            received += len(data)
        return b''.join(chunks)

    def read1(self, size=-1):
        return self.read(size)

    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def readline(self, size=-1):
        result = bytearray()
        while size < 0 or len(result) < size:
            data = self.read(1)
            result.extend(data)
            if not data or data == b'\n':
                break
        return bytes(result)

    def readlines(self, hint=-1):
        result, count = [], 0
        for line in self:
            result.append(line)
            count += len(line)
            if hint > 0 and count >= hint:
                break
        return result

    def __iter__(self):
        return self

    def __next__(self):
        line = self.readline()
        if not line:
            raise StopIteration
        return line


class RedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_302(self, req, fp, code, msg, headers):
        # urllib rejects file: before redirect_request; make that refusal typed and
        # sticky too, even when discovery callers catch ordinary HTTP errors.
        target = headers.get('location') or headers.get('uri')
        state = current()
        if state is not None and target:
            try:
                target = urllib.parse.urljoin(req.full_url, target)
                if urllib.parse.urlsplit(target).scheme.lower() != 'https':
                    state.admit(target)
            except Exception as exc:
                state.remember(exc)
                raise
        return super().http_error_302(req, fp, code, msg, headers)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        state = current()
        destination = state.admit(newurl) if state is not None else None
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if state is not None and redirected is not None:
            redirected._ravel_destination = destination
            redirected._ravel_url = redirected.full_url
        return redirected


def _member_path(root, name):
    relative = PurePosixPath(name)
    if not name or '\\' in name or relative.is_absolute() or '..' in relative.parts:
        raise ValueError('unsafe acquisition archive member')
    target = root.joinpath(*relative.parts)
    if target == root or any(path.is_symlink() for path in (target, *target.parents)):
        raise ValueError('acquisition archive member traverses a link')
    return target


def download_archive(url, output):
    """Download and extract bounded zip/tar regular members through governed HTTP."""
    from . import discovery_http
    state = current()
    if state is None:
        raise ValueError('archive acquisition requires a governed scope')
    try:
        root = Path(output).absolute()
        with ExitStack() as stack:
            stream = stack.enter_context(tempfile.NamedTemporaryFile(dir=root.parent))
            with discovery_http.open_url(url, accept='application/octet-stream') as response:
                received = 0
                while data := response.read(min(CHUNK, state.max_bytes - received + 1)):
                    received += len(data)
                    if received > state.max_bytes:
                        raise ValueError('controller acquisition response byte ceiling exceeded')
                    stream.write(data)
            stream.flush()
            stream.seek(0)
            members, archive = [], None
            if zipfile.is_zipfile(stream):
                archive = stack.enter_context(zipfile.ZipFile(stream))
                for info in archive.infolist():
                    mode = info.external_attr >> 16
                    if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                        raise ValueError('acquisition archive contains a link or special member')
                    members.append((_member_path(root, info.filename), info.file_size,
                                    info.is_dir(), info))
            else:
                stream.seek(0)
                archive = stack.enter_context(tarfile.open(fileobj=stream, mode='r:*'))
                for info in archive:
                    state.remaining()
                    if not (info.isfile() or info.isdir()):
                        raise ValueError('acquisition archive contains a link or special member')
                    members.append((_member_path(root, info.name), info.size, info.isdir(), info))
            if len({str(path) for path, _, _, _ in members}) != len(members):
                raise ValueError('duplicate acquisition archive member')
            if sum(size for _, size, directory, _ in members if not directory) > state.max_bytes:
                raise ValueError('acquisition archive uncompressed byte ceiling exceeded')
            for path, size, directory, info in members:
                state.remaining()
                _member_path(root, str(path.relative_to(root)))
                if directory:
                    private_files.mkdir(path)
                    continue
                private_files.mkdir(path.parent)
                source = archive.open(info) if isinstance(archive, zipfile.ZipFile) else archive.extractfile(info)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with source, os.fdopen(fd, 'wb') as destination:
                    received = 0
                    while payload := source.read(min(CHUNK, size - received + 1)):
                        received += len(payload)
                        if received > size:
                            break
                        destination.write(payload)
                    if received != size:
                        raise ValueError('acquisition archive member size mismatch')
                state.remaining()
            return [str(path.relative_to(root)) for path, _, directory, _ in members if not directory]
    except Exception as exc:
        state.remember(exc)
        raise
