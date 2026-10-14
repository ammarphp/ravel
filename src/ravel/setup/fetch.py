"""Verified downloads with a content-addressed cache and safe archive extraction.

Every download is pinned by size (when known) and sha256 or the upstream md5.
Verified files live at ``<cache>/sha256/<digest>``; a resumed or repeated
install finds them there and makes no network request. A file whose digest
does not match its pin is moved to ``<cache>/quarantine`` and the install stops.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile

CHUNK = 1024 * 1024


class FetchError(RuntimeError):
    """A download could not be obtained."""


class DigestMismatch(FetchError):
    """A downloaded file does not match its pin; it has been quarantined."""

    def __init__(self, url, expected, actual, quarantined):
        self.url, self.expected, self.actual, self.quarantined = url, expected, actual, quarantined
        super().__init__(f"digest mismatch for {url}: expected {expected}, got {actual}; "
                         f"the file was moved to {quarantined} and nothing was extracted")


class UnsafeArchive(FetchError):
    """An archive member would escape its destination."""


def _default_open(url, timeout):
    request = urllib.request.Request(url, headers={"User-Agent": "ravel-installer"})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https enforced by caller


class Fetcher:
    """Download pinned files into a content-addressed cache.

    ``opener(url, timeout)`` returns a readable binary response; tests inject a
    fake. ``offline=True`` refuses any network access and uses the cache only.
    """

    def __init__(self, cache_dir, *, opener=None, offline=False, timeout=60):
        self.cache = Path(cache_dir)
        self.opener = opener or _default_open
        self.offline = offline
        self.timeout = timeout
        self.network_requests = []

    def cached_path(self, pin):
        if pin.get("sha256"):
            return self.cache / "sha256" / pin["sha256"]
        return self.cache / "md5" / pin["md5"]

    def _digest_ok(self, path, pin):
        actual = file_digests(path)
        if "size" in pin and pin["size"] and actual["size"] != pin["size"]:
            return False, actual
        if pin.get("sha256"):
            return actual["sha256"] == pin["sha256"], actual
        return actual["md5"] == pin["md5"], actual

    def fetch(self, url, pin):
        """Return the verified cached path for ``url`` pinned by ``pin``."""
        if pin.get("blocked_reason"):
            raise FetchError(f"{url} has no verified pin: {pin['blocked_reason']}")
        target = self.cached_path(pin)
        if target.is_file():
            ok, actual = self._digest_ok(target, pin)
            if ok:
                return target
            self._quarantine(target, url, pin, actual)
        if self.offline:
            raise FetchError(f"offline mode: {url} is not in the download cache ({target})")
        if not url.startswith("https://"):
            raise FetchError("only https downloads are allowed: " + url)
        tmp_dir = self.cache / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=tmp_dir, prefix="download-")
        self.network_requests.append(url)
        try:
            with os.fdopen(handle, "wb") as out, self.opener(url, self.timeout) as response:
                limit = (pin.get("size") or 0) + 1 if pin.get("size") else None
                written = 0
                while True:
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    written += len(chunk)
                    if limit is not None and written > limit:
                        break
                    out.write(chunk)
        except OSError as error:
            Path(temporary).unlink(missing_ok=True)
            raise FetchError(f"download failed for {url}: {error}") from error
        ok, actual = self._digest_ok(Path(temporary), pin)
        if not ok:
            self._quarantine(Path(temporary), url, pin, actual)
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, target)
        return target

    def _quarantine(self, path, url, pin, actual):
        quarantine = self.cache / "quarantine"
        quarantine.mkdir(parents=True, exist_ok=True)
        name = PurePosixPath(url.split("?", 1)[0]).name or "download"
        destination = quarantine / f"{name}.{actual['sha256'][:16]}"
        os.replace(path, destination)
        expected = pin.get("sha256") or ("md5:" + pin.get("md5", ""))
        got = actual["sha256"] if pin.get("sha256") else "md5:" + actual["md5"]
        if pin.get("size") and actual["size"] != pin["size"]:
            expected = f"{expected} ({pin['size']} bytes)"
            got = f"{got} ({actual['size']} bytes)"
        raise DigestMismatch(url, expected, got, destination)


def file_digests(path):
    sha, md5, size = hashlib.sha256(), hashlib.md5(usedforsecurity=False), 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            sha.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return {"sha256": sha.hexdigest(), "md5": md5.hexdigest(), "size": size}


def _member_path(name, strip):
    path = PurePosixPath(name)
    if path.is_absolute() or name.startswith(("/", "\\")) or ".." in path.parts:
        raise UnsafeArchive("archive member escapes its destination: " + name)
    parts = path.parts[strip:]
    return PurePosixPath(*parts) if parts else None


def safe_extract(archive, destination, *, strip=0):
    """Extract a tar or zip archive into a new directory, refusing unsafe members.

    Absolute paths, ``..`` components, links pointing outside the destination,
    device files and FIFOs are refused before anything is written.
    """
    archive, destination = Path(archive), Path(destination)
    if destination.exists():
        raise FileExistsError("extraction destination already exists: " + str(destination))
    if zipfile.is_zipfile(archive):
        return _extract_zip(archive, destination, strip)
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        plan = []
        for member in members:
            relative = _member_path(member.name, strip)
            if relative is None:
                continue
            if member.isdev() or member.isfifo():
                raise UnsafeArchive("archive contains a device or FIFO: " + member.name)
            if member.issym() or member.islnk():
                target = PurePosixPath(member.linkname)
                base = relative.parent if member.issym() else PurePosixPath()
                resolved = base / target
                if target.is_absolute() or _escapes(resolved):
                    raise UnsafeArchive("archive link escapes its destination: " + member.name)
                if member.islnk():
                    member_target = _member_path(member.linkname, strip)
                    if member_target is None:
                        raise UnsafeArchive("hard link to a stripped member: " + member.name)
            plan.append((member, relative))
        destination.mkdir(parents=True)
        for member, relative in plan:
            out = destination / Path(*relative.parts)
            if member.isdir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                os.symlink(member.linkname, out)
            elif member.islnk():
                source = destination / Path(*_member_path(member.linkname, strip).parts)
                shutil.copy2(source, out)
            else:
                with tar.extractfile(member) as source, out.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
                os.chmod(out, member.mode & 0o755 | 0o600)
    return destination


def _escapes(path):
    depth = 0
    for part in path.parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        elif part not in (".", ""):
            depth += 1
    return False


def _extract_zip(archive, destination, strip):
    with zipfile.ZipFile(archive) as bundle:
        plan = []
        for info in bundle.infolist():
            relative = _member_path(info.filename, strip)
            if relative is None:
                continue
            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                raise UnsafeArchive("zip symlinks are not supported: " + info.filename)
            plan.append((info, relative))
        destination.mkdir(parents=True)
        for info, relative in plan:
            out = destination / Path(*relative.parts)
            if info.is_dir():
                out.mkdir(parents=True, exist_ok=True)
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, out.open("wb") as sink:
                shutil.copyfileobj(source, sink)
            permissions = (info.external_attr >> 16) & 0o777
            if permissions:
                os.chmod(out, permissions & 0o755 | 0o600)
    return destination
