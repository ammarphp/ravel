"""Host adapters for the evaluation harness (slice design §9, §13).

- ``base``: AdapterResult, the Adapter base class, launch and raw-stream helpers.
- ``fake`` / ``fake_subject``: the synthetic fake host and its stdlib subject script (WP06).
- ``claude_cli``: Claude Code CLI adapter (WP09); ``codex_cli``: Codex CLI adapter (WP08).

Standard library only. No adapter test calls a model; the CLI adapters are exercised with
mocked executables and synthetic recorded-format streams.
"""
from .base import Adapter, AdapterResult, HostDriftError

__all__ = ["Adapter", "AdapterResult", "HostDriftError"]
