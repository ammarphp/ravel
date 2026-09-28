"""The real-host credential exception (smoke spec WI-5, §1.6): stat-only checks, the nonblocking read, the token
variants and the post-run sweep with its redaction manifest.

Every token here is a SYNTHETIC dummy (``sk-ant-oat01-SYNTHETIC-<32 hex>``) in a 0600 file under a 0700 scratch
directory; no test reads the real credential path.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
from pathlib import Path

import pytest

from governance import credentials
from governance.canonical import ContractError, sha256_bytes


def dummy_token() -> str:
    return "sk-ant-oat01-SYNTHETIC-" + secrets.token_hex(16)


@pytest.fixture
def cred(tmp_path):
    directory = tmp_path / "ravel-eval"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    token = dummy_token()
    path = directory / "claude-oauth-token"
    path.write_text(token + "\n")
    path.chmod(0o600)
    return path, token


def pieces(token: str) -> list:
    """The token, every 8-character piece of it and its length: none may appear in a message."""
    return [token] + [token[i:i + 8] for i in range(0, len(token) - 7, 4)]


def assert_silent(text: str, token: str):
    assert all(piece not in text for piece in pieces(token)), text


def test_a_well_kept_file_is_read_with_one_trailing_newline_stripped(cred):
    path, token = cred
    assert credentials.read_credential(path) == token
    path.write_text(token)
    assert credentials.read_credential(path) == token
    assert credentials.check_credential_file(path) == {"present": True, "ok": True, "problems": []}


def make_fifo(path):
    os.mkfifo(path, 0o600)


def make_hardlink(path):
    os.link(path, path.parent / "second-link")


def make_symlink(path):
    target = path.parent / "target"
    path.rename(target)
    path.symlink_to(target)


def make_group_readable(path):
    path.chmod(0o640)


def make_empty(path):
    path.write_bytes(b"")


def make_oversize(path):
    path.write_bytes(b"a" * (credentials.MAX_BYTES + 1))


def make_bad_charset(path):
    path.write_text("sk-ant-oat01 SYNTHETIC with spaces and more than twenty\n")


def make_two_newlines(path):
    path.write_text(dummy_token() + "\n\n")


def make_two_tokens(path):
    path.write_text(dummy_token() + "\n" + dummy_token() + "\n")


def make_short(path):
    path.write_text("sk-ant-short\n")


def make_non_ascii(path):
    path.write_bytes(("sk-ant-oat01-SYNTHETIC-" + "é" * 20).encode())


def make_missing(path):
    path.unlink()


def make_group_writable_dir(path):
    path.parent.chmod(0o770)


@pytest.mark.parametrize("damage, message", [
    (make_missing, "does not exist"), (make_symlink, "symbolic link"), (make_hardlink, "more than one link"),
    (make_group_readable, "group or others"), (make_empty, "empty"), (make_oversize, "larger than"),
    (make_bad_charset, "single token"), (make_two_newlines, "single token"), (make_two_tokens, "single token"),
    (make_short, "single token"), (make_non_ascii, "ASCII"), (make_group_writable_dir, "group- or world-writable"),
])
def test_an_unsafe_or_malformed_file_is_refused_with_a_generic_message(cred, damage, message):
    path, token = cred
    damage(path)
    with pytest.raises(credentials.CredentialError, match=message) as refused:
        credentials.read_credential(path)
    for text in (str(refused.value), repr(refused.value), repr(refused.value.args)):
        assert_silent(text, token)
    check = credentials.check_credential_file(path)
    content_only = damage in (make_bad_charset, make_two_newlines, make_two_tokens, make_short, make_non_ascii)
    assert check["ok"] is content_only and bool(check["problems"]) is not content_only   # stat never reads content
    assert_silent(json.dumps(check), token)
    parent = path.parent
    parent.chmod(0o700)


def test_a_file_owned_by_another_user_is_refused(cred, monkeypatch):
    path, token = cred
    real = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real + 1)
    with pytest.raises(credentials.CredentialError, match="not owned by this user"):
        credentials.read_credential(path)
    assert not credentials.check_credential_file(path)["ok"]


def test_a_fifo_is_refused_without_hanging(cred):
    path, _ = cred
    path.unlink()
    make_fifo(path)
    with pytest.raises(credentials.CredentialError, match="not a regular file"):
        credentials.read_credential(path)   # O_NONBLOCK: the open returns at once with no writer
    check = credentials.check_credential_file(path)
    assert check["present"] and "the credential file is not a regular file" in check["problems"]


def test_check_never_opens_the_file(cred, monkeypatch):
    path, _ = cred
    opened = []
    real_open = os.open

    def spy(name, *args, **kwargs):
        opened.append(os.fspath(name))
        return real_open(name, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy)
    assert credentials.check_credential_file(path)["ok"]
    assert str(path) not in opened


def test_a_relative_path_is_refused(cred):
    with pytest.raises(ContractError, match="absolute path"):
        credentials.read_credential("claude-oauth-token")


def test_variants_cover_every_encoding_at_every_alignment():
    token = dummy_token().encode()
    forms = credentials.variants(token)
    assert set(forms) == set(credentials.VARIANT_NAMES)
    samples = {"raw": b"x" + token + b"y", "hex_lower": token.hex().encode(), "hex_upper": token.hex().upper().encode(),
               "utf16le": token.decode().encode("utf-16-le"), "utf16be": token.decode().encode("utf-16-be")}
    for name, data in samples.items():
        assert credentials.count_variants(b"prefix" + data + b"suffix", token), name
    for encode in (base64.b64encode, base64.urlsafe_b64encode):
        for pad in range(3):
            blob = encode(b"q" * pad + token + b"tail")
            assert credentials.count_variants(blob, token), (encode.__name__, pad)
    slashed = b"sk-ant-oat01/SYNTHETIC/" + secrets.token_hex(16).encode()
    assert credentials.count_variants(json.dumps({"k": slashed.decode()}).replace("/", "\\/").encode(), slashed) == {
        "json_escaped": 1}
    assert credentials.count_variants(b"nothing here", token) == {}


def test_redact_bytes_replaces_every_variant_and_counts_them():
    token = dummy_token().encode()
    data = b"|".join([token, token.hex().encode(), base64.b64encode(b"zz" + token), token.decode().encode("utf-16-le")])
    redacted, counts = credentials.redact_bytes(data, token)
    assert credentials.count_variants(redacted, token) == {}
    assert counts == {"raw": 1, "hex_lower": 1, "base64_std": 1, "utf16le": 1}
    assert redacted.count(credentials.REDACTION) == 4


@pytest.fixture
def tree(tmp_path):
    token = dummy_token()
    root = tmp_path / "state"
    (root / "config" / "projects").mkdir(parents=True)
    (root / "config" / ".credentials.json").write_text(json.dumps({"accessToken": token}))
    (root / "config" / "projects" / "session.jsonl").write_bytes(b'{"x":"' + token.encode().hex().encode() + b'"}\n')
    (root / "config" / "utf16.bin").write_bytes(("note " + token).encode("utf-16-le"))
    (root / "config" / "b64.txt").write_bytes(base64.b64encode(b"k" + token.encode() + b"v"))
    (root / "config" / "clean.txt").write_text("SYNTHETIC nothing secret")
    (root / "config" / "clean.txt").chmod(0o640)
    (root / "config" / ".credentials.json").chmod(0o600)
    return root, token


KEY = b"SYNTHETIC campaign secret for keyed digests, 48 bytes"


def keyed(data):
    return credentials.keyed_digest(KEY, data, credentials.REDACTION_PURPOSE)


def test_sweep_finds_and_redacts_every_variant_and_keeps_modes(tree):
    root, token = tree
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    found = credentials.sweep({"host_state": str(root)}, token.encode(), redact=True, byte_cap=1 << 20,
                              pre_digest=keyed)
    assert found["incomplete"] is False and found["skipped"] == []
    hits = {h["path"]: h["counts"] for h in found["hits"]}
    assert hits == {"config/.credentials.json": {"raw": 1}, "config/projects/session.jsonl": {"hex_lower": 1},
                    "config/utf16.bin": {"utf16le": 1}, "config/b64.txt": {"base64_std": 1}}
    manifest = {r["path"]: r for r in found["redactions"]}
    assert set(manifest) == set(hits)
    for rel, entry in manifest.items():
        path = root / rel
        # E-80: the bytes before redaction are kept only as a keyed digest, never a plain (checkable) hash
        assert "pre_sha256" not in entry and entry["pre_hmac_sha256"] == keyed(before[path])
        assert entry["pre_hmac_sha256"] != sha256_bytes(before[path])
        assert entry["post_sha256"] == sha256_bytes(path.read_bytes())
        assert entry["counts_by_variant"] == hits[rel]
        assert credentials.count_variants(path.read_bytes(), token.encode()) == {}
    assert stat.S_IMODE((root / "config" / ".credentials.json").stat().st_mode) == 0o600
    assert (root / "config" / "clean.txt").read_bytes() == before[root / "config" / "clean.txt"]
    assert_silent(json.dumps(found), token)
    again = credentials.sweep({"host_state": str(root)}, token.encode(), redact=True, byte_cap=1 << 20)
    assert again["hits"] == [] and again["redactions"] == []


def test_sweep_without_redaction_leaves_the_files(tree):
    root, token = tree
    found = credentials.sweep({"s": str(root)}, token.encode(), redact=False, byte_cap=1 << 20)
    assert len(found["hits"]) == 4 and found["redactions"] == []
    assert token in (root / "config" / ".credentials.json").read_text()


def test_sweep_never_follows_links_and_reports_names_and_link_targets(tree, tmp_path):
    root, token = tree
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text(token)
    (root / "link-to-outside").symlink_to(outside)
    (root / "link-to-file").symlink_to(outside / "secret.txt")
    (root / "dangling").symlink_to(token)          # the token as a link target
    (root / ("name-" + token)).write_text("clean")   # the token as a file name
    found = credentials.sweep({"s": str(root)}, token.encode(), redact=True, byte_cap=1 << 20)
    where = {(h["path"], h["where"]) for h in found["hits"]}
    assert ("dangling", "link_target") in where
    assert not any(h["path"].startswith("link-to-outside/") for h in found["hits"])
    assert (outside / "secret.txt").read_text() == token      # never followed, never rewritten
    assert found["incomplete"] is False
    assert_silent(json.dumps(found), token)                     # a name holding the token is shown redacted
    assert ("name-" + credentials.REDACTION.decode(), "name") in {(h["path"], h["where"]) for h in found["hits"]}


def test_sweep_skips_fifos_and_hardlinks_and_honours_the_byte_cap(tree):
    root, token = tree
    os.mkfifo(root / "config" / "pipe")
    os.link(root / "config" / "clean.txt", root / "config" / "clean-link.txt")
    found = credentials.sweep({"s": str(root)}, token.encode(), redact=False, byte_cap=1 << 20)
    kinds = {(s["path"], s["kind"]) for s in found["skipped"]}
    assert ("config/pipe", "special_file") in kinds
    assert ("config/clean-link.txt", "hardlinked") in kinds and ("config/clean.txt", "hardlinked") in kinds
    assert found["incomplete"] is True       # a hardlinked file was not read
    capped = credentials.sweep({"s": str(root)}, token.encode(), redact=False, byte_cap=64)
    assert capped["incomplete"] is True and any(s["kind"] == "byte_cap" for s in capped["skipped"])
    assert capped["bytes_read"] <= 64


def test_sweep_of_a_missing_root_is_not_incomplete(tmp_path):
    token = dummy_token().encode()
    found = credentials.sweep({"gone": str(tmp_path / "gone")}, token, redact=False, byte_cap=10)
    assert found == {"hits": [], "redactions": [], "skipped": [{"root": "gone", "path": ".", "kind": "missing"}],
                     "incomplete": False, "bytes_read": 0}


def test_an_unwritable_hit_is_reported_and_marks_the_sweep_incomplete(tree):
    root, token = tree
    directory = root / "config" / "projects"
    directory.chmod(0o555)
    try:
        found = credentials.sweep({"s": str(root)}, token.encode(), redact=True, byte_cap=1 << 20)
    finally:
        directory.chmod(0o755)
    assert any(s == {"root": "s", "path": "config/projects/session.jsonl", "kind": "redaction_failed"}
               for s in found["skipped"])
    assert found["incomplete"] is True
    assert "config/projects/session.jsonl" in {h["path"] for h in found["hits"]}


def test_keyed_digests_need_a_key_and_separate_purposes():
    data = b"SYNTHETIC token-bearing bytes"
    assert credentials.keyed_digest(KEY, data, credentials.REDACTION_PURPOSE) != \
        credentials.keyed_digest(KEY, data, credentials.FINGERPRINT_PURPOSE)
    assert credentials.keyed_digest(KEY, data, credentials.REDACTION_PURPOSE) != hashlib.sha256(data).hexdigest()
    for bad in ((b"short", data, "p"), (KEY, "text", "p"), (KEY, data, ""), (KEY, data, "a\0b")):
        with pytest.raises(ContractError):
            credentials.keyed_digest(*bad)


def test_nothing_the_module_returns_describes_the_token(cred):
    path, token = cred
    for thing in (credentials.check_credential_file(path), credentials.variants(token.encode()).keys()):
        assert_silent(repr(thing), token)
    assert Path(path).read_text().strip() == token   # the fixture itself is intact


def test_names_holding_the_token_are_renamed_and_values_redacted(tmp_path):
    """A file or directory NAMED with the token (a hit the sweep cannot rewrite) is renamed with the token replaced;
    a journaled value is redacted through a JSON round trip. Nothing returned carries the token."""
    token = b"sk-ant-oat01-SYNTHETIC-" + b"0123456789abcdef" * 2
    root = tmp_path / "root"
    (root / f"dir-{token.decode()}").mkdir(parents=True)
    (root / f"dir-{token.decode()}" / f"file-{token.hex()}.txt").write_text("SYNTHETIC\n")
    (root / "REDACTED-clash").write_text("x")
    records = credentials.redact_names(root, token)
    assert all(set(r) == {"path", "post_sha256", "counts_by_variant", "renamed"} for r in records)   # no old-name hash
    assert all(r["post_sha256"] != hashlib.sha256(token).hexdigest() for r in records)
    assert {r["counts_by_variant"].popitem()[0] for r in records} == {"raw", "hex_lower"}
    assert all(r["renamed"] and token.decode() not in r["path"] for r in records)
    names = [p.name for p in root.rglob("*")]
    assert not any(token.decode() in n or token.hex() in n for n in names)
    assert (root / "dir-[REDACTED:host-credential]" / "file-[REDACTED:host-credential].txt").is_file()
    value, counts = credentials.redact_value({"target": f"{token.decode()}:443", "n": 1}, token)
    assert value == {"target": "[REDACTED:host-credential]:443", "n": 1} and counts == {"raw": 1}
    assert credentials.redact_value({"n": 1}, token) == ({"n": 1}, {})
