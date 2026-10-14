"""Digest record of the agent host configuration files, so a silent rewrite is noticed.

Wolfram AgentTools' deploy command once rewrote ``~/.codex/config.toml``. The installer never calls it.
It also records a digest of each host configuration file at the first install, and ``ravel doctor``
warns when one differs. Only digests are stored, never contents.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

HOST_CONFIG_FILES = (".codex/config.toml", ".claude/settings.json")
RECORD_NAME = "host-config-digests.json"


def _digest(path):
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def current(home):
    return {name: _digest(Path(home) / name) for name in HOST_CONFIG_FILES}


def record(config_dir, home, *, replace=False):
    """Write the baseline digests. An existing record is kept unless ``replace`` is set."""
    path = Path(config_dir) / RECORD_NAME
    if path.is_file() and not replace:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "files": current(home)}, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return True


def warnings(config_dir, home):
    """One plain sentence per host configuration file whose digest differs from the baseline."""
    path = Path(config_dir) / RECORD_NAME
    if not path.is_file():
        return []
    try:
        recorded = json.loads(path.read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError):
        return ["the host-config digest record is unreadable; rerun `ravel doctor --record-host-config`"]
    now = current(home)
    out = []
    for name, before in sorted(recorded.items()):
        after = now.get(name, _digest(Path(home) / name))
        if after != before:
            what = "was removed" if after is None else "appeared" if before is None else "changed"
            out.append(f"~/{name} {what} since the installer recorded it. RAVEL never edits it; check what did, "
                       f"then run `ravel doctor --record-host-config` to accept the new state.")
    return out
