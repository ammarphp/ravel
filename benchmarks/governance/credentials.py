"""The one real-host credential exception: a subscription setup-token file (smoke spec WI-5, §1.6).

A real-host campaign declares one credential by variable NAME and file path (``host_launch.credential``). The
coordinator reads that file in exactly three places: the run-start validation (which discards the value), the
recording launcher (which puts it only into the environment dict it hands ``isolation.launch``) and the
resume-time sweep. Everything here is built so that no message, exception, repr, return value or record ever
carries the value, a substring of it, its length or its prefix:

- ``check_credential_file`` stats the path (lstat and stat only; it never opens the file) for build and
  preflight, which report only that a credential is present and well-kept.
- ``read_credential`` opens with O_NOFOLLOW|O_NONBLOCK (a symlink fails, a FIFO cannot hang the coordinator),
  checks the open file (regular, one link, the coordinator's own, no group or world bits, 1..MAX_BYTES bytes),
  reads at most MAX_BYTES + 1 bytes, strips exactly one trailing newline and requires an ASCII token.
- ``variants``, ``redact_bytes`` and ``sweep`` find the token after a run: raw, JSON-escaped, base64 (standard
  and URL-safe, each at the three byte alignments a token can take inside a larger encoded blob), hex (both
  cases) and UTF-16 (both byte orders), in file contents, file names and symbolic-link targets, and rewrite the
  files that hold it. Arbitrary transformations (compression, encryption, splitting) are not detected.
- ``keyed_digest``: the only digest ever kept of token-bearing bytes (a redaction record's pre-redaction bytes, a
  launch's credential fingerprint) is an HMAC-SHA256 under the campaign secret with a purpose label, never a plain
  hash: a plain sha256 of a small file holding the token, or of a name equal to it, would be a permanent check value
  for a retained, year-long secret in sealed evidence (E-80). Name redactions keep no digest of the old name.

Standard library only.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import os
import re
import stat
import tempfile

from .canonical import ContractError, require

MAX_BYTES = 4096
TOKEN = re.compile(r"[A-Za-z0-9._~+/=-]{20,4096}")
REDACTION = b"[REDACTED:host-credential]"
SWEEP_BYTE_CAP = 512 << 20
VARIANT_NAMES = ("raw", "json_escaped", "base64_std", "base64_urlsafe", "hex_lower", "hex_upper", "utf16le",
                 "utf16be")
FINGERPRINT_PURPOSE = "ravel-credential-fingerprint"   # keyed_digest purposes (domain separation)
REDACTION_PURPOSE = "ravel-redaction-pre"


def keyed_digest(key: bytes, data: bytes, purpose: str) -> str:
    """HMAC-SHA256 (hex) of ``data`` under ``key`` for one ``purpose`` label (never a plain hash of secret bytes)."""
    require(isinstance(key, bytes) and len(key) >= 32, "keyed_digest: a key of at least 32 bytes is required")
    require(isinstance(data, bytes) and isinstance(purpose, str) and purpose and "\0" not in purpose,
            "keyed_digest: bytes and a purpose label are required")
    return hmac.new(key, purpose.encode() + b"\0" + data, hashlib.sha256).hexdigest()


class CredentialError(ContractError):
    """A credential file is missing, unsafe or malformed. Messages are generic: never the content, its length
    or any prefix of it."""


# ---------------------------------------------------------------- the file

def _mode_problems(info, *, uid) -> list:
    problems = []
    if not stat.S_ISREG(info.st_mode):
        problems.append("the credential file is not a regular file")
    if info.st_nlink != 1:
        problems.append("the credential file has more than one link")
    if info.st_uid != uid:
        problems.append("the credential file is not owned by this user")
    if info.st_mode & 0o077:
        problems.append("the credential file is readable or writable by group or others (mode must be 0600)")
    if not 0 < info.st_size <= MAX_BYTES:
        problems.append(f"the credential file is empty or larger than {MAX_BYTES} bytes")
    return problems


def _parent_problems(path) -> list:
    try:
        parent = os.lstat(os.path.dirname(path))
    except OSError as exc:
        return [f"the credential directory cannot be inspected ({exc.strerror})"]
    problems = []
    if not stat.S_ISDIR(parent.st_mode):
        problems.append("the credential directory is not a directory (or is a symbolic link)")
    if parent.st_mode & 0o022:
        problems.append("the credential directory is group- or world-writable")
    if parent.st_uid != os.getuid():
        problems.append("the credential directory is not owned by this user")
    return problems


def _clean(path) -> str:
    text = os.fspath(path)
    require(isinstance(text, str) and os.path.isabs(text) and "\x00" not in text,
            "credential file: an absolute path is required")
    return os.path.normpath(text)


def check_credential_file(path) -> dict:
    """{"present", "ok", "problems"} for the credential path from lstat and stat only (never opened): a
    regular file, not a symbolic link, one link, owned by this user, no group or world bits, 1..MAX_BYTES bytes,
    in a directory owned by this user that is neither group- nor world-writable."""
    path = _clean(path)
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {"present": False, "ok": False, "problems": ["the credential file does not exist"]}
    except OSError as exc:
        return {"present": False, "ok": False,
                "problems": [f"the credential file cannot be inspected ({exc.strerror})"]}
    if stat.S_ISLNK(info.st_mode):
        problems = ["the credential file is a symbolic link"]
    else:
        problems = _mode_problems(info, uid=os.getuid())
    problems += _parent_problems(path)
    return {"present": True, "ok": not problems, "problems": problems}


def read_credential(path) -> str:
    """The token in the credential file, or CredentialError with a generic message. The file is opened
    O_RDONLY|O_NOFOLLOW|O_CLOEXEC|O_NONBLOCK and checked through its descriptor (a regular file with one link,
    owned by this user, mode & 0o077 == 0, 1..MAX_BYTES bytes); at most MAX_BYTES + 1 bytes are read, exactly
    one trailing newline is stripped, and the rest must be ASCII matching TOKEN."""
    path = _clean(path)
    problems = _parent_problems(path)
    if problems:
        raise CredentialError(problems[0])
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    except FileNotFoundError:
        raise CredentialError("the credential file does not exist") from None
    except OSError as exc:
        if exc.errno == errno.ELOOP or os.path.islink(path):
            raise CredentialError("the credential file is a symbolic link") from None
        raise CredentialError(f"the credential file cannot be opened ({exc.strerror})") from None
    try:
        problems = _mode_problems(os.fstat(fd), uid=os.getuid())
        if problems:
            raise CredentialError(problems[0])
        chunks, total = [], 0
        while total <= MAX_BYTES:
            try:
                chunk = os.read(fd, MAX_BYTES + 1 - total)
            except BlockingIOError:
                raise CredentialError("the credential file could not be read without blocking") from None
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError as exc:
        raise CredentialError(f"the credential file could not be read ({exc.strerror})") from None
    finally:
        os.close(fd)
    data = b"".join(chunks)
    if len(data) > MAX_BYTES:
        raise CredentialError(f"the credential file is larger than {MAX_BYTES} bytes")
    if data.endswith(b"\n"):
        data = data[:-1]
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError:
        raise CredentialError("the credential file does not hold an ASCII token") from None
    if TOKEN.fullmatch(text) is None:
        raise CredentialError("the credential file does not hold a single token (20 or more token characters, "
                              "one optional trailing newline)")
    return text


# ---------------------------------------------------------------- finding and removing the token

def _b64_cores(token: bytes, encode) -> list:
    """The part of a base64 encoding that depends only on the token's bytes, for each of the three offsets
    (mod 3) at which the token can start inside a larger encoded blob."""
    cores, n = [], len(token)
    for pad in range(3):
        encoded = encode(b"\x00" * pad + token + b"\x00\x00")
        start, end = -(-8 * pad // 6), (8 * (pad + n)) // 6
        cores.append(encoded[start:end])
    return cores


def variants(token: bytes) -> dict:
    """{variant name: [encoded forms]} of the token (VARIANT_NAMES); a form equal to one already listed under
    an earlier name is not repeated (the JSON form of a token without '/' is the raw token)."""
    require(isinstance(token, bytes) and TOKEN.fullmatch(token.decode("ascii", "replace")) is not None,
            "variants: a token (bytes) is required")
    forms = {"raw": [token], "json_escaped": [token.replace(b"/", b"\\/")],
             "base64_std": _b64_cores(token, base64.b64encode),
             "base64_urlsafe": _b64_cores(token, base64.urlsafe_b64encode),
             "hex_lower": [token.hex().encode()], "hex_upper": [token.hex().upper().encode()],
             "utf16le": [token.decode("ascii").encode("utf-16-le")],
             "utf16be": [token.decode("ascii").encode("utf-16-be")]}
    seen, out = set(), {}
    for name in VARIANT_NAMES:
        out[name] = [f for f in dict.fromkeys(forms[name]) if f and f not in seen]
        seen.update(out[name])
    return out


def _ordered(token: bytes) -> list:
    """(name, form) pairs, longest form first: a longer form is replaced before any form it contains."""
    pairs = [(name, form) for name, forms in variants(token).items() for form in forms]
    return sorted(pairs, key=lambda pair: (-len(pair[1]), VARIANT_NAMES.index(pair[0])))


def count_variants(data: bytes, token: bytes) -> dict:
    """{variant name: occurrences} in data (only names that occur); nothing about where or what."""
    counts = {}
    for name, form in _ordered(token):
        n = data.count(form)
        if n:
            counts[name] = counts.get(name, 0) + n
            data = data.replace(form, b"\x00")
    return counts


def redact_bytes(data: bytes, token: bytes) -> tuple:
    """(data with every variant replaced by REDACTION, {variant name: replacements})."""
    counts = {}
    for name, form in _ordered(token):
        n = data.count(form)
        if n:
            counts[name] = counts.get(name, 0) + n
            data = data.replace(form, REDACTION)
    return data, counts


def _rewrite(path: str, info, data: bytes) -> None:
    """Replace path atomically with data, keeping its mode; refuses when path changed since it was read."""
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".ravel-redact-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, stat.S_IMODE(info.st_mode))
        now = os.lstat(path)
        if (now.st_dev, now.st_ino) != (info.st_dev, info.st_ino):
            raise OSError("the file changed while it was being redacted")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def sweep(roots: dict, token: bytes, *, redact: bool, byte_cap: int = SWEEP_BYTE_CAP, pre_digest=None) -> dict:
    """Search every labelled root ({label: absolute path}) for the token's variants without following links.

    Returns {"hits", "redactions", "skipped", "incomplete", "bytes_read"}. hits: [{root, path, where, counts}]
    where ``where`` is "content", "name" or "link_target" and counts is {variant name: n}; paths are relative
    to their root, and a path whose name holds the token is shown with it replaced by REDACTION. redactions
    (redact=True): [{root, path, post_sha256, counts_by_variant}, plus pre_hmac_sha256 = pre_digest(the bytes before
    redaction) when ``pre_digest`` is given (a keyed digest: keyed_digest)] for every content hit rewritten
    atomically with the same mode (a name or link-target hit cannot be rewritten and stays a hit). skipped: [{root, path, kind}] for entries not read: FIFOs, sockets and devices (reported;
    they hold no file content), and unreadable directories, unreadable or hardlinked regular files, files past
    the byte cap and files whose redaction failed, each of which also sets ``incomplete``. Files are opened
    O_NOFOLLOW|O_NONBLOCK and read only when they are the regular, single-link inode lstat saw. A missing root
    is skipped with kind "missing" (nothing to search, not incomplete). Nothing returned or raised carries the
    token or any of its variants."""
    require(isinstance(roots, dict) and all(isinstance(k, str) for k in roots), "sweep: roots must be a dict")
    require(type(byte_cap) is int and byte_cap >= 0, "sweep: byte_cap must be a nonnegative int")
    forms = [form for _, form in _ordered(token)]
    result = {"hits": [], "redactions": [], "skipped": [], "incomplete": False, "bytes_read": 0}

    def shown(rel):   # a reported path never carries the token: a name holding it is shown redacted
        raw = os.fsencode(rel)
        return os.fsdecode(redact_bytes(raw, token)[0]) if any(f in raw for f in forms) else rel

    def skip(label, rel, kind, incomplete):
        result["skipped"].append({"root": label, "path": shown(rel), "kind": kind})
        result["incomplete"] = result["incomplete"] or incomplete

    def name_hits(label, rel, text, where):
        raw = os.fsencode(text)
        counts = count_variants(raw, token) if any(f in raw for f in forms) else {}
        if counts:
            result["hits"].append({"root": label, "path": shown(rel), "where": where, "counts": counts})

    for label in sorted(roots):
        root = os.path.normpath(os.fspath(roots[label]))
        require(os.path.isabs(root), f"sweep: root {label} must be absolute")
        try:
            top = os.lstat(root)
        except FileNotFoundError:
            skip(label, ".", "missing", False)
            continue
        except OSError:
            skip(label, ".", "unreadable", True)
            continue
        if not stat.S_ISDIR(top.st_mode):
            skip(label, ".", "not_a_directory", True)
            continue
        errors = []
        for current, dirs, names in os.walk(root, onerror=errors.append):
            dirs.sort()
            for name in sorted(dirs + names):
                path = os.path.join(current, name)
                rel = os.path.relpath(path, root)
                name_hits(label, rel, name, "name")
                try:
                    info = os.lstat(path)
                except OSError:
                    skip(label, rel, "unreadable", True)
                    continue
                if stat.S_ISDIR(info.st_mode):
                    continue
                if stat.S_ISLNK(info.st_mode):
                    try:
                        name_hits(label, rel, os.readlink(path), "link_target")
                    except OSError:
                        skip(label, rel, "unreadable_link", True)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    skip(label, rel, "special_file", False)
                    continue
                if info.st_nlink != 1:
                    skip(label, rel, "hardlinked", True)
                    continue
                if result["bytes_read"] + info.st_size > byte_cap:
                    skip(label, rel, "byte_cap", True)
                    continue
                try:
                    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
                except OSError:
                    skip(label, rel, "unreadable", True)
                    continue
                try:
                    opened = os.fstat(fd)
                    if ((opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                            or not stat.S_ISREG(opened.st_mode)):
                        skip(label, rel, "changed_during_sweep", True)
                        continue
                    chunks, total, limit = [], 0, byte_cap - result["bytes_read"]
                    while True:
                        chunk = os.read(fd, min(1 << 20, limit - total + 1))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                        if total > limit:
                            break
                except OSError:
                    skip(label, rel, "unreadable", True)
                    continue
                finally:
                    os.close(fd)
                if total > limit:
                    skip(label, rel, "byte_cap", True)
                    continue
                result["bytes_read"] += total
                data = b"".join(chunks)
                counts = count_variants(data, token)
                if not counts:
                    continue
                result["hits"].append({"root": label, "path": shown(rel), "where": "content", "counts": counts})
                if redact:
                    redacted, replaced = redact_bytes(data, token)
                    try:
                        _rewrite(path, info, redacted)
                    except OSError:
                        skip(label, rel, "redaction_failed", True)
                        continue
                    entry = {"root": label, "path": shown(rel), "post_sha256": hashlib.sha256(redacted).hexdigest(),
                             "counts_by_variant": replaced}
                    if pre_digest is not None:
                        entry["pre_hmac_sha256"] = pre_digest(data)
                    result["redactions"].append(entry)
        for error in errors:
            where = os.path.relpath(error.filename, root) if getattr(error, "filename", None) else "."
            skip(label, where, "unreadable_directory", True)
    return result


def redact_names(root, token: bytes) -> list:
    """Rename every entry under ``root`` whose NAME holds a variant of the token (a hit ``sweep`` can find but not
    rewrite), bottom-up and without following links, replacing each variant with REDACTION. Returns one record per
    name, {path (relative, after the rename), post_sha256 (of the new name bytes), counts_by_variant, renamed}; no
    digest of the old name is kept (a name equal to the token would make it sha256(token)). ``renamed`` is False when
    the redacted name already exists (the entry keeps its name, and the caller treats the sweep as incomplete).
    Nothing returned carries the token."""
    root = os.path.normpath(os.fspath(root))
    require(os.path.isabs(root), "redact_names: an absolute root is required")
    forms = [form for _, form in _ordered(token)]
    records = []
    if not os.path.isdir(root) or os.path.islink(root):
        return records
    for current, dirs, names in os.walk(root, topdown=False):
        for name in dirs + names:
            raw = os.fsencode(name)
            if not any(form in raw for form in forms):
                continue
            new, counts = redact_bytes(raw, token)
            old_path, new_path = os.path.join(current, name), os.path.join(current, os.fsdecode(new))
            renamed = not os.path.lexists(new_path)
            if renamed:
                os.rename(old_path, new_path)
            rel = os.path.relpath(new_path if renamed else old_path, root)
            shown = os.fsdecode(redact_bytes(os.fsencode(rel), token)[0])
            records.append({"path": shown, "post_sha256": hashlib.sha256(new).hexdigest(), "counts_by_variant": counts,
                            "renamed": renamed})
    return records


def redact_value(value, token: bytes):
    """(value, counts): a JSON-serializable value with every variant of the token replaced by REDACTION in its strings
    (a canonical JSON round trip); counts {variant: n} is empty when nothing was found."""
    import json
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    redacted, counts = redact_bytes(data, token)
    return (json.loads(redacted) if counts else value), counts
