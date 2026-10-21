"""Scoped acquisition admission, redirects, budgets and ordinary archive members."""
import io
import os
import stat
import socket
import ssl
import tarfile
import urllib.request
import urllib.error
import zipfile

import pytest

from ravel.workflow import acquisition_http as acquisition
from ravel.workflow import discovery_http, hepdata_fetch, restriction_guard


@pytest.fixture
def governed(monkeypatch, tmp_path):
    admissions = []
    monkeypatch.setattr(acquisition.socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('8.8.8.8', 443))])
    def admit(tool, descriptor, **kwargs):
        admissions.append((tool, descriptor, kwargs))
    monkeypatch.setattr(restriction_guard, 'require', admit)
    return tmp_path, admissions


def scoped(root, max_bytes=4096, wall_seconds=10):
    return acquisition.scope(root, root / 'out', {'classes': ['public-metadata']},
                             max_bytes, wall_seconds)


def test_policy_precedes_transport_and_audits_only_admitted_requests(governed, monkeypatch):
    root, admissions = governed
    events = []
    def transport(req, **kwargs):
        assert admissions[-1][1]['url'] == req.full_url
        assert kwargs['timeout'] <= 10
        events.append(req.full_url)
        return io.BytesIO(b'{}')
    monkeypatch.setattr(discovery_http, '_urlopen', transport)
    with scoped(root) as audit:
        assert discovery_http.get_json('https://example.test/data') == {}
    assert audit['bytes'] == 2
    assert len(audit['requests']) == 1
    assert audit['requests'][0]['url'] == events[0]
    assert len(audit['requests'][0]['descriptor_sha256']) == 64
    assert admissions[0][0] == 'controller-acquisition'
    assert admissions[0][2] == {'rundir': root, 'output': root / 'out'}
    assert acquisition.current() is None


def test_refused_policy_never_reaches_transport_or_audit(governed, monkeypatch):
    root, _ = governed
    def refuse(*args, **kwargs):
        raise restriction_guard.SourceRestricted('source forbidden')
    monkeypatch.setattr(restriction_guard, 'require', refuse)
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: pytest.fail('transport reached'))
    with pytest.raises(restriction_guard.SourceRestricted):
        with scoped(root) as audit:
            discovery_http.open_url('https://example.test/forbidden')
    assert audit == {'requests': [], 'bytes': 0}


def test_swallowed_source_refusal_remains_fatal(governed, monkeypatch):
    root, _ = governed
    def refuse(*args, **kwargs):
        raise restriction_guard.SourceRestricted('source forbidden')
    monkeypatch.setattr(restriction_guard, 'require', refuse)
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: pytest.fail('transport reached'))
    with pytest.raises(restriction_guard.SourceRestricted):
        with scoped(root):
            result = discovery_http.inspire_hepdata_ids('1')
            assert result['status'] == 'ERROR'


def test_redirect_target_admitted_before_following(governed):
    root, admissions = governed
    with scoped(root) as audit:
        request = acquisition.RedirectHandler().redirect_request(
            urllib.request.Request('https://example.test/start'), None, 302, 'Found', {},
            'https://example.test/target')
        assert request.full_url == 'https://example.test/target'
    assert admissions[0][1]['url'] == audit['requests'][0]['url'] == request.full_url


def test_redirect_refusal_precedes_target_open(governed, monkeypatch):
    root, _ = governed
    followed = []
    original = urllib.request.HTTPRedirectHandler.redirect_request
    def follow(*args, **kwargs):
        followed.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, 'redirect_request', follow)
    def refuse(*args, **kwargs):
        raise restriction_guard.SourceRestricted('redirect forbidden')
    monkeypatch.setattr(restriction_guard, 'require', refuse)
    with pytest.raises(restriction_guard.SourceRestricted):
        with scoped(root) as audit:
            acquisition.RedirectHandler().redirect_request(
                urllib.request.Request('https://example.test/start'), None, 302, 'Found', {},
                'https://example.test/forbidden')
    assert followed == [] and audit['requests'] == []


def test_real_transport_uses_scoped_redirect_handler(governed, monkeypatch):
    root, _ = governed
    handlers = []
    class Opener:
        def open(self, request, timeout):
            return io.BytesIO(b'ok')
    def build(*args):
        handlers.extend(args)
        return Opener()
    monkeypatch.setattr(urllib.request, 'build_opener', build)
    with scoped(root):
        with discovery_http.open_url('https://example.test/data') as response:
            assert response.read() == b'ok'
    assert any(isinstance(handler, acquisition.RedirectHandler) for handler in handlers)
    assert any(isinstance(handler, urllib.request.HTTPSHandler) for handler in handlers)


def test_byte_ceiling_exact_boundary_and_bounded_read(governed, monkeypatch):
    root, _ = governed
    sizes = []
    class Stream(io.BytesIO):
        def read1(self, size=-1):
            sizes.append(size)
            return super().read1(size)
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: Stream(b'abcd'))
    with scoped(root, max_bytes=4) as audit:
        with discovery_http.open_url('https://example.test/data') as response:
            assert response.read() == b'abcd'
            assert response.read() == b''
    assert sizes and all(0 < size <= 5 and size <= 65536 for size in sizes)
    assert audit['bytes'] == 4


def test_cumulative_ceiling_and_swallowed_read_failure(governed, monkeypatch):
    root, _ = governed
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: io.BytesIO(b'abc'))
    with pytest.raises(ValueError, match='byte ceiling'):
        with scoped(root, max_bytes=5) as audit:
            assert discovery_http.open_url('https://example.test/one').read() == b'abc'
            try:
                discovery_http.open_url('https://example.test/two').read()
            except ValueError:
                pass
    assert audit['bytes'] == 6


def test_deadline_before_transport_and_after_read(governed, monkeypatch):
    root, _ = governed
    clock = [100.0]
    monkeypatch.setattr(acquisition.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: pytest.fail('late transport'))
    with pytest.raises(TimeoutError):
        with scoped(root, wall_seconds=1) as audit:
            clock[0] = 101.0
            discovery_http.open_url('https://example.test/data')
    assert audit['requests'] == []
    class Slow(io.BytesIO):
        def read1(self, size=-1):
            clock[0] += 2
            return super().read1(size)
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: Slow(b'a'))
    with pytest.raises(TimeoutError):
        with scoped(root, wall_seconds=1):
            try:
                discovery_http.open_url('https://example.test/data').read()
            except TimeoutError:
                pass


@pytest.mark.parametrize('max_bytes,seconds', [(0, 1), (-1, 1), (True, 1), (1, 0),
                                                (1, float('inf')), (1, float('nan'))])
def test_invalid_bounds_refuse(max_bytes, seconds, tmp_path):
    with pytest.raises(ValueError):
        with scoped(tmp_path, max_bytes, seconds):
            pytest.fail('invalid scope entered')


def test_default_transport_outside_scope_is_unchanged(monkeypatch):
    response = io.BytesIO(b'legacy')
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: response)
    assert discovery_http.open_url('https://example.test/data') is response


def archive_bytes(kind, name='models/model.json', link=False, payload=b'{}'):
    output = io.BytesIO()
    if kind == 'zip':
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            info = zipfile.ZipInfo(name)
            if link:
                info.create_system = 3
                info.external_attr = 0o120777 << 16
            archive.writestr(info, payload)
    else:
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            info = tarfile.TarInfo(name)
            if link:
                info.type = tarfile.SYMTYPE if link == 'symbolic' else tarfile.LNKTYPE
                info.linkname = 'elsewhere'
                archive.addfile(info)
            else:
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


@pytest.mark.parametrize('kind', ['zip', 'tar'])
def test_safe_archive_positive(governed, monkeypatch, kind):
    root, _ = governed
    body = archive_bytes(kind)
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: io.BytesIO(body))
    with scoped(root) as audit:
        paths = acquisition.download_archive('https://example.test/models', root / 'out')
    assert paths == ['models/model.json']
    assert (root / 'out/models/model.json').read_bytes() == b'{}'
    assert audit['bytes'] == len(body)


@pytest.mark.parametrize('kind,name,link', [('zip', '../escape', False), ('zip', '/escape', False),
                                         ('zip', 'model', True), ('tar', '../escape', False),
                                         ('tar', '/escape', False), ('tar', 'model', 'symbolic'),
                                         ('tar', 'model', 'hard')])
def test_archive_traversal_and_links_refuse(governed, monkeypatch, kind, name, link):
    root, _ = governed
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: io.BytesIO(archive_bytes(kind, name, link)))
    with pytest.raises(ValueError):
        with scoped(root):
            acquisition.download_archive('https://example.test/models', root / 'out')
    assert not (root / 'out').exists()


def test_archive_uncompressed_ceiling_before_extraction(governed, monkeypatch):
    root, _ = governed
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('model.json', b'a' * 5000)
    assert len(output.getvalue()) < 1024
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: io.BytesIO(output.getvalue()))
    with pytest.raises(ValueError, match='uncompressed'):
        with scoped(root, max_bytes=1024):
            acquisition.download_archive('https://example.test/models', root / 'out')
    assert not (root / 'out').exists()


def test_acquired_members_start_private_under_permissive_umask(governed, monkeypatch):
    root, _ = governed
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: io.BytesIO(archive_bytes('zip')))
    previous = os.umask(0)
    try:
        with scoped(root):
            acquisition.download_archive('https://example.test/model', root / 'out')
    finally:
        os.umask(previous)
    for path in (root / 'out', *(root / 'out').rglob('*')):
        assert stat.S_IMODE(path.stat().st_mode) == (0o700 if path.is_dir() else 0o600)


def test_existing_output_symlink_refuses(governed, monkeypatch):
    root, _ = governed
    (root / 'elsewhere').mkdir()
    (root / 'out').symlink_to(root / 'elsewhere', target_is_directory=True)
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: io.BytesIO(archive_bytes('zip')))
    with pytest.raises(ValueError):
        with scoped(root):
            acquisition.download_archive('https://example.test/models', root / 'out')
    assert list((root / 'elsewhere').iterdir()) == []


def test_hepdata_scoped_clients_skip_thirdparty_downloaders(governed, monkeypatch):
    root, _ = governed
    calls = []
    monkeypatch.setattr(hepdata_fetch, '_require', lambda *a, **k: None)
    monkeypatch.setattr(discovery_http, 'fetch_hepdata_record', lambda *a: {
        'status': 'OK', 'ref': 'ins1', 'url': 'https://example.test/record',
        'record': {'data_tables': [], 'resources': [{'url': 'https://example.test/model',
                                                   'file_type': 'pyhf'}]}})
    monkeypatch.setattr(hepdata_fetch, '_tables_via_hepdata_cli', lambda *a: pytest.fail('thirdparty tables'))
    monkeypatch.setattr(hepdata_fetch, 'fetch_tables_via_record_data', lambda *a: calls.append('tables'))
    monkeypatch.setattr(acquisition, 'download_archive', lambda *a: calls.append('likelihood'))
    with scoped(root) as audit:
        hepdata_fetch.main(['--inspire', 'ins1', '--out', str(root / 'out'), '--tables', '--download-likelihood'])
    assert calls == ['likelihood', 'tables']
    assert audit == {'requests': [], 'bytes': 0}  # stubs provide no HTTP admission evidence


def test_caught_http_absence_is_not_a_sticky_safety_failure(governed, monkeypatch):
    root, _ = governed
    def absent(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 404, 'Not Found', {}, None)
    monkeypatch.setattr(discovery_http, '_urlopen', absent)
    with scoped(root) as audit:
        try:
            discovery_http.open_url('https://example.test/absent')
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
    assert len(audit['requests']) == 1
    assert audit['requests'][0]['url'] == 'https://example.test/absent'
    assert audit['bytes'] == 0


def test_trickling_read_stops_at_total_deadline(governed, monkeypatch):
    root, _ = governed
    clock, reads = [0.0], []
    monkeypatch.setattr(acquisition.time, 'monotonic', lambda: clock[0])
    class Trickle:
        def read1(self, size):
            reads.append(size)
            clock[0] += 0.4
            return b'x'
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: Trickle())
    with pytest.raises(TimeoutError):
        with scoped(root, wall_seconds=1) as audit:
            discovery_http.open_url('https://example.test/trickle').read()
    assert len(reads) == 3
    assert audit['bytes'] == 3
    assert all(size <= 65536 for size in reads)


def test_zero_read_uses_no_transport_read_and_socket_timeout_is_capped(governed, monkeypatch):
    from types import SimpleNamespace
    root, _ = governed
    timeouts = []
    class Stream(io.BytesIO):
        fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=timeouts.append)))
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: Stream(b'ab'))
    with scoped(root):
        response = discovery_http.open_url('https://example.test/data')
        assert response.read(0) == b''
        assert timeouts == []
        assert response.read(1) == b'a'
    assert len(timeouts) == 1 and 0 < timeouts[0] <= 10


@pytest.mark.parametrize('url', [
    'file:///etc/passwd', 'http://example.test/data',
    'https://user@example.test/data', 'https://user:secret@example.test/data',
    'https://example.test:bad/data', 'https://example.test:0/data',
    'https://example.test/line\nbreak', 'https://[fe80::1%25en0]/data',
])
def test_destination_url_refusal_is_sticky_before_transport(governed, monkeypatch, url):
    root, _ = governed
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: pytest.fail('transport reached'))
    with pytest.raises(acquisition.DestinationRefused, match='Remedy:'):
        with scoped(root) as audit:
            try:
                discovery_http.open_url(url)
            except acquisition.DestinationRefused:
                pass
    assert audit['requests'] == []


@pytest.mark.parametrize('addresses', [
    ['127.0.0.1'], ['10.0.0.1'], ['169.254.169.254'], ['0.0.0.0'],
    ['192.168.1.1'], ['100.64.0.1'], ['224.0.0.1'], ['::1'], ['fe80::1'],
    ['fc00::1'], ['fec0::1'], ['::ffff:127.0.0.1'], ['::ffff:169.254.169.254'],
    ['8.8.8.8', '10.0.0.1'],
])
def test_all_dns_answers_must_be_global_and_metadata_cannot_grant(governed, monkeypatch, addresses):
    root, _ = governed
    monkeypatch.setattr(acquisition.socket, 'getaddrinfo', lambda *a, **k: [
        (socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM,
         socket.IPPROTO_TCP, '', (address, 443)) for address in addresses])
    monkeypatch.setattr(discovery_http, '_urlopen', lambda *a, **k: pytest.fail('transport reached'))
    with pytest.raises(acquisition.DestinationRefused, match='trusted operator grant'):
        with acquisition.scope(root, root / 'out', {'allow_private': True,
                              'operator_grant': {'trusted': True}}, 4096, 10):
            discovery_http.open_url('https://example.test/data')


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'http://example.test/plain',
                               'https://user@example.test/secret', 'https://private.test/data'])
def test_redirect_destination_refused_before_follow(governed, monkeypatch, url):
    root, _ = governed
    if 'private.test' in url:
        monkeypatch.setattr(acquisition.socket, 'getaddrinfo', lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('127.0.0.1', 443))])
    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, 'redirect_request',
                        lambda *a, **k: pytest.fail('unsafe redirect followed'))
    with pytest.raises(acquisition.DestinationRefused):
        with scoped(root):
            acquisition.RedirectHandler().redirect_request(
                urllib.request.Request('https://example.test/start'), None, 302, 'Found', {}, url)


def inert_network(monkeypatch, responses):
    """Exercise the real urllib/http.client stack without DNS or socket I/O."""
    connected, sent, sni = [], [], []
    class Socket:
        def __init__(self, *args):
            self.body = responses[len(connected)]
        def settimeout(self, value):
            pass
        def setsockopt(self, *args):
            pass
        def connect(self, address):
            connected.append(address)
        def sendall(self, data):
            sent.append(data)
        def makefile(self, *args):
            return io.BytesIO(self.body)
        def close(self):
            pass
    context = ssl.create_default_context()
    def wrap(sock, *, server_hostname, **kwargs):
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        sni.append(server_hostname)
        return sock
    monkeypatch.setattr(context, 'wrap_socket', wrap)
    monkeypatch.setattr(discovery_http, 'SSL_CONTEXT', context)
    monkeypatch.setattr(acquisition.socket, 'socket', Socket)
    return connected, sent, sni


def test_real_connect_pins_dns_and_preserves_verified_tls_and_host(governed, monkeypatch):
    root, _ = governed
    resolutions = []
    def resolve(host, port, **kwargs):
        resolutions.append((host, port))
        if len(resolutions) != 1:
            pytest.fail('connection re-resolved admitted DNS (rebinding exposure)')
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('8.8.8.8', port))]
    monkeypatch.setattr(acquisition.socket, 'getaddrinfo', resolve)
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:9999')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9999')
    connected, sent, sni = inert_network(monkeypatch, [b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok'])
    with scoped(root) as audit:
        assert discovery_http.open_url('https://example.test:8443/data').read() == b'ok'
    assert resolutions == [('example.test', 8443)]
    assert connected == [('8.8.8.8', 8443)]
    assert sni == ['example.test']
    assert b'Host: example.test:8443\r\n' in b''.join(sent)
    assert b'CONNECT' not in b''.join(sent)
    assert audit['requests'][0]['destination_address'] == '8.8.8.8'


@pytest.mark.parametrize('target', ['https://private.test/metadata', 'file:///etc/passwd',
                                   'http://private.test/metadata',
                                   'https://user@example.test/metadata'])
def test_real_redirect_cannot_connect_to_private_target(governed, monkeypatch, target):
    root, _ = governed
    def resolve(host, port, **kwargs):
        address = '8.8.8.8' if host == 'example.test' else '169.254.169.254'
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (address, port))]
    monkeypatch.setattr(acquisition.socket, 'getaddrinfo', resolve)
    connected, _, _ = inert_network(monkeypatch, [
        f'HTTP/1.1 302 Found\r\nLocation: {target}\r\nContent-Length: 0\r\n\r\n'.encode()])
    with pytest.raises(acquisition.DestinationRefused):
        with scoped(root) as audit:
            try:
                discovery_http.open_url('https://example.test/start')
            except acquisition.DestinationRefused:
                pass
    assert connected == [('8.8.8.8', 443)]
    assert len(audit['requests']) == 1


def test_unverified_tls_context_refuses_before_socket(governed, monkeypatch):
    root, _ = governed
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    monkeypatch.setattr(discovery_http, 'SSL_CONTEXT', context)
    monkeypatch.setattr(acquisition.socket, 'socket', lambda *a, **k: pytest.fail('socket created'))
    with pytest.raises(acquisition.DestinationRefused, match='TLS verification'):
        with scoped(root):
            discovery_http.open_url('https://example.test/data')
